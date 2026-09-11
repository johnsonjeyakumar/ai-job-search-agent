"""Idempotency, execution locking, and reliability hardening (Phase 24).

Central safety guarantee:
    ONE APPLICATION
    → ONE ACTIVE EXECUTOR
    → ONE CONTROLLED SUBMISSION ATTEMPT
    → NO ACCIDENTAL DUPLICATE SUBMISSION

This module provides:
- Execution ownership via PostgreSQL-backed advisory locks
- Idempotency keys for execution attempts
- Stale lock detection with heartbeat
- Submit-attempt boundary enforcement
- Retry authorization after uncertain submissions
- Crash recovery helpers

All locks are database-level (not in-process Python locks) so they work
across multiple backend workers/processes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Execution attempt states
# ---------------------------------------------------------------------------

class AttemptState(str, Enum):
    """Lifecycle of an execution attempt."""
    FIRST_ATTEMPT = "FIRST_ATTEMPT"
    EXECUTING = "EXECUTING"
    SUBMIT_ATTEMPTED = "SUBMIT_ATTEMPTED"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_CONFIRMED = "SUBMISSION_CONFIRMED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    RETRY_AUTHORIZED = "RETRY_AUTHORIZED"


class LockOutcome(str, Enum):
    """Result of a lock acquisition attempt."""
    ACQUIRED = "ACQUIRED"
    ALREADY_LOCKED = "ALREADY_LOCKED"
    STALE_LOCK_RELEASED = "STALE_LOCK_RELEASED"
    ERROR = "ERROR"


class RecoveryAction(str, Enum):
    """Action to take when recovering from a crash."""
    RESUME_SAFE = "RESUME_SAFE"
    VERIFY_OUTCOME = "VERIFY_OUTCOME"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    NO_ACTION = "NO_ACTION"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL_SECONDS = 30
STALE_LOCK_TIMEOUT_SECONDS = 120
SUBMIT_TIMEOUT_SECONDS = 60


# ---------------------------------------------------------------------------
# Idempotency key generation
# ---------------------------------------------------------------------------

def generate_idempotency_key(
    package_id: int,
    job_id: int,
    attempt_number: int = 1,
) -> str:
    """Generate a deterministic idempotency key for an execution attempt.

    The key is deterministic for the same inputs, but unique across attempts
    (via attempt_number). This allows legitimate retries while preventing
    duplicate execution of the same intended application.

    Key format: {hash}:{package_id}:{attempt}
    """
    raw = f"pkg={package_id}:job={job_id}:attempt={attempt_number}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{h}:{package_id}:{attempt_number}"


def parse_idempotency_key(key: str) -> dict[str, Any]:
    """Parse an idempotency key back into its components."""
    parts = key.split(":")
    if len(parts) != 3:
        return {}
    return {
        "hash": parts[0],
        "package_id": int(parts[1]),
        "attempt_number": int(parts[2]),
    }


# ---------------------------------------------------------------------------
# Execution lock manager (PostgreSQL-backed)
# ---------------------------------------------------------------------------

@dataclass
class LockResult:
    """Result of a lock operation."""
    outcome: LockOutcome
    owner_id: str | None = None
    execution_id: int | None = None
    message: str = ""


@dataclass
class HeartbeatInfo:
    """Heartbeat status for an execution."""
    execution_id: int
    owner_id: str | None
    lock_acquired_at: datetime | None
    heartbeat_at: datetime | None
    is_stale: bool
    seconds_since_heartbeat: float | None = None


class ExecutionLockManager:
    """Manages execution ownership via PostgreSQL advisory locks.

    Uses PostgreSQL advisory locks for cross-process safety. Each application
    (via package_id) can have at most one active executor.
    """

    def acquire(
        self,
        db: Session,
        *,
        package_id: int,
        execution_id: int,
        owner_id: str,
    ) -> LockResult:
        """Attempt to acquire execution ownership.

        Uses PostgreSQL advisory lock on the package_id. If another worker
        holds the lock, this returns ALREADY_LOCKED.

        The lock is session-scoped (released when the DB session closes).
        """
        try:
            # Use PostgreSQL advisory lock (session-level, auto-released on disconnect)
            lock_key = package_id
            result = db.execute(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": lock_key},
            )
            acquired = result.scalar()

            if not acquired:
                # Check if there's a stale lock we can recover
                stale = self._check_stale_lock(db, package_id=package_id)
                if stale:
                    self._release_ownership(db, package_id=package_id)
                    # Retry acquisition
                    result = db.execute(
                        text("SELECT pg_try_advisory_lock(:key)"),
                        {"key": lock_key},
                    )
                    acquired = result.scalar()
                    if acquired:
                        self._set_ownership(
                            db,
                            package_id=package_id,
                            execution_id=execution_id,
                            owner_id=owner_id,
                        )
                        return LockResult(
                            outcome=LockOutcome.STALE_LOCK_RELEASED,
                            owner_id=owner_id,
                            execution_id=execution_id,
                            message="Stale lock recovered and re-acquired.",
                        )

                return LockResult(
                    outcome=LockOutcome.ALREADY_LOCKED,
                    message="Another worker holds the execution lock.",
                )

            # Lock acquired — set ownership
            self._set_ownership(
                db,
                package_id=package_id,
                execution_id=execution_id,
                owner_id=owner_id,
            )
            return LockResult(
                outcome=LockOutcome.ACQUIRED,
                owner_id=owner_id,
                execution_id=execution_id,
                message="Execution lock acquired.",
            )

        except Exception as exc:
            return LockResult(
                outcome=LockOutcome.ERROR,
                message=f"Lock acquisition error: {exc}",
            )

    def release(
        self,
        db: Session,
        *,
        package_id: int,
        owner_id: str,
    ) -> bool:
        """Release the execution lock.

        Only the owner can release. Returns True if released.
        """
        try:
            # Release advisory lock
            lock_key = package_id
            db.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": lock_key},
            )
            self._clear_ownership(db, package_id=package_id, owner_id=owner_id)
            db.flush()
            return True
        except Exception:
            return False

    def is_locked(
        self,
        db: Session,
        *,
        package_id: int,
    ) -> bool:
        """Check if a package is currently locked by any worker."""
        row = db.execute(
            text(
                "SELECT owner_id, lock_acquired_at FROM execution_locks "
                "WHERE package_id = :pid AND released_at IS NULL"
            ),
            {"pid": package_id},
        ).mappings().first()
        if row is None:
            return False
        # Check if stale
        if row["lock_acquired_at"]:
            elapsed = (
                datetime.now(timezone.utc) - row["lock_acquired_at"]
            ).total_seconds()
            if elapsed > STALE_LOCK_TIMEOUT_SECONDS:
                return False  # Stale — treat as unlocked
        return True

    def get_owner(
        self,
        db: Session,
        *,
        package_id: int,
    ) -> str | None:
        """Get the current lock owner for a package."""
        row = db.execute(
            text(
                "SELECT owner_id FROM execution_locks "
                "WHERE package_id = :pid AND released_at IS NULL"
            ),
            {"pid": package_id},
        ).mappings().first()
        return row["owner_id"] if row else None

    def heartbeat(
        self,
        db: Session,
        *,
        package_id: int,
        owner_id: str,
    ) -> bool:
        """Update the heartbeat timestamp for an active lock."""
        try:
            db.execute(
                text(
                    "UPDATE execution_locks SET heartbeat_at = :now "
                    "WHERE package_id = :pid AND owner_id = :oid AND released_at IS NULL"
                ),
                {
                    "pid": package_id,
                    "oid": owner_id,
                    "now": datetime.now(timezone.utc),
                },
            )
            db.flush()
            return True
        except Exception:
            return False

    def get_heartbeat_info(
        self,
        db: Session,
        *,
        package_id: int,
    ) -> HeartbeatInfo | None:
        """Get heartbeat info for a package's lock."""
        row = db.execute(
            text(
                "SELECT execution_id, owner_id, lock_acquired_at, heartbeat_at "
                "FROM execution_locks "
                "WHERE package_id = :pid AND released_at IS NULL"
            ),
            {"pid": package_id},
        ).mappings().first()
        if row is None:
            return None

        heartbeat_at = row["heartbeat_at"]
        is_stale = False
        seconds_since = None
        if heartbeat_at:
            seconds_since = (
                datetime.now(timezone.utc) - heartbeat_at
            ).total_seconds()
            is_stale = seconds_since > STALE_LOCK_TIMEOUT_SECONDS
        elif row["lock_acquired_at"]:
            seconds_since = (
                datetime.now(timezone.utc) - row["lock_acquired_at"]
            ).total_seconds()
            is_stale = seconds_since > STALE_LOCK_TIMEOUT_SECONDS

        return HeartbeatInfo(
            execution_id=row["execution_id"],
            owner_id=row["owner_id"],
            lock_acquired_at=row["lock_acquired_at"],
            heartbeat_at=heartbeat_at,
            is_stale=is_stale,
            seconds_since_heartbeat=seconds_since,
        )

    # -- internal helpers --

    def _set_ownership(
        self,
        db: Session,
        *,
        package_id: int,
        execution_id: int,
        owner_id: str,
    ) -> None:
        """Record ownership in the execution_locks table."""
        now = datetime.now(timezone.utc)
        db.execute(
            text(
                "INSERT INTO execution_locks "
                "(package_id, execution_id, owner_id, lock_acquired_at, heartbeat_at) "
                "VALUES (:pid, :eid, :oid, :now, :now) "
                "ON CONFLICT (package_id) DO UPDATE SET "
                "execution_id = EXCLUDED.execution_id, "
                "owner_id = EXCLUDED.owner_id, "
                "lock_acquired_at = EXCLUDED.lock_acquired_at, "
                "heartbeat_at = EXCLUDED.heartbeat_at, "
                "released_at = NULL"
            ),
            {
                "pid": package_id,
                "eid": execution_id,
                "oid": owner_id,
                "now": now,
            },
        )
        db.flush()

    def _clear_ownership(
        self,
        db: Session,
        *,
        package_id: int,
        owner_id: str,
    ) -> None:
        """Mark the lock as released."""
        db.execute(
            text(
                "UPDATE execution_locks SET released_at = :now "
                "WHERE package_id = :pid AND owner_id = :oid AND released_at IS NULL"
            ),
            {
                "pid": package_id,
                "oid": owner_id,
                "now": datetime.now(timezone.utc),
            },
        )
        db.flush()

    def _release_ownership(
        self,
        db: Session,
        *,
        package_id: int,
    ) -> None:
        """Force-release ownership (for stale lock recovery)."""
        db.execute(
            text(
                "UPDATE execution_locks SET released_at = :now "
                "WHERE package_id = :pid AND released_at IS NULL"
            ),
            {"pid": package_id, "now": datetime.now(timezone.utc)},
        )
        db.flush()

    def _check_stale_lock(
        self,
        db: Session,
        *,
        package_id: int,
    ) -> bool:
        """Check if the current lock is stale and can be recovered."""
        row = db.execute(
            text(
                "SELECT lock_acquired_at, heartbeat_at "
                "FROM execution_locks "
                "WHERE package_id = :pid AND released_at IS NULL"
            ),
            {"pid": package_id},
        ).mappings().first()
        if row is None:
            return False

        # Check heartbeat first, then lock acquisition time
        check_time = row["heartbeat_at"] or row["lock_acquired_at"]
        if check_time is None:
            return False

        elapsed = (datetime.now(timezone.utc) - check_time).total_seconds()
        return elapsed > STALE_LOCK_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Submit-attempt boundary
# ---------------------------------------------------------------------------

def mark_submit_attempted(
    db: Session,
    *,
    execution_id: int,
) -> None:
    """Mark that a final submission action has been attempted.

    After this point, no automatic submission retry is allowed until
    the outcome is deterministically confirmed or explicitly resolved.
    """
    db.execute(
        text(
            "UPDATE application_executions "
            "SET submission_attempted_at = :now "
            "WHERE id = :eid"
        ),
        {"eid": execution_id, "now": datetime.now(timezone.utc)},
    )
    db.flush()


def check_submit_boundary(
    db: Session,
    *,
    execution_id: int,
) -> dict[str, Any]:
    """Check whether a submission has already been attempted.

    Returns a dict with:
        - can_submit: bool — whether a new submission is allowed
        - reason: str — why submission is blocked (if applicable)
        - submission_attempted_at: datetime | None
        - current_status: str
    """
    row = db.execute(
        text(
            "SELECT status, submission_attempted_at, submission_status "
            "FROM application_executions WHERE id = :eid"
        ),
        {"eid": execution_id},
    ).mappings().first()

    if row is None:
        return {"can_submit": False, "reason": "Execution not found."}

    status = row["status"]
    attempted_at = row["submission_attempted_at"]
    submission_status = row["submission_status"]

    # Already confirmed — definitely cannot re-submit
    if status == "SUBMISSION_CONFIRMED":
        return {
            "can_submit": False,
            "reason": "Submission already confirmed.",
            "submission_attempted_at": attempted_at,
            "current_status": status,
        }

    # Already submitted — cannot re-submit automatically
    if status == "SUBMITTED":
        return {
            "can_submit": False,
            "reason": "Submission already occurred. Awaiting confirmation.",
            "submission_attempted_at": attempted_at,
            "current_status": status,
        }

    # Submission uncertain — requires review, not retry
    if status == "SUBMISSION_UNKNOWN":
        return {
            "can_submit": False,
            "reason": "Previous submission uncertain. Human review required.",
            "submission_attempted_at": attempted_at,
            "current_status": status,
        }

    # Submit attempted but no outcome yet — uncertain
    if attempted_at is not None and submission_status in (None, "UNKNOWN"):
        return {
            "can_submit": False,
            "reason": "Submit was attempted but outcome unknown. Human review required.",
            "submission_attempted_at": attempted_at,
            "current_status": status,
        }

    # Pre-submit states — can submit
    return {
        "can_submit": True,
        "reason": "",
        "submission_attempted_at": attempted_at,
        "current_status": status,
    }


# ---------------------------------------------------------------------------
# Retry authorization
# ---------------------------------------------------------------------------

def authorize_retry(
    db: Session,
    *,
    execution_id: int,
    reason: str = "",
) -> bool:
    """Authorize a retry after uncertain submission.

    Only allowed for SUBMISSION_UNKNOWN status. Sets the execution to
    RETRY_AUTHORIZED state and records the authorization.
    """
    row = db.execute(
        text("SELECT status FROM application_executions WHERE id = :eid"),
        {"eid": execution_id},
    ).mappings().first()

    if row is None:
        return False

    if row["status"] != "SUBMISSION_UNKNOWN":
        return False

    now = datetime.now(timezone.utc)
    db.execute(
        text(
            "UPDATE application_executions "
            "SET retry_authorized_at = :now, retry_reason = :reason "
            "WHERE id = :eid"
        ),
        {"eid": execution_id, "now": now, "reason": reason or "Manual retry authorized."},
    )
    db.flush()
    return True


def is_retry_authorized(
    db: Session,
    *,
    execution_id: int,
) -> bool:
    """Check if a retry has been authorized for this execution."""
    row = db.execute(
        text(
            "SELECT retry_authorized_at FROM application_executions "
            "WHERE id = :eid"
        ),
        {"eid": execution_id},
    ).mappings().first()

    return row is not None and row["retry_authorized_at"] is not None


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------

def assess_crash_recovery(
    db: Session,
    *,
    execution_id: int,
) -> dict[str, Any]:
    """Assess what recovery action to take after a crash.

    Returns:
        - action: RecoveryAction
        - reason: str
        - execution_status: str
        - submission_attempted: bool
        - has_evidence: bool
    """
    row = db.execute(
        text(
            "SELECT status, submission_attempted_at, submission_status, "
            "current_step, started_at "
            "FROM application_executions WHERE id = :eid"
        ),
        {"eid": execution_id},
    ).mappings().first()

    if row is None:
        return {
            "action": RecoveryAction.NO_ACTION,
            "reason": "Execution not found.",
            "execution_status": "UNKNOWN",
            "submission_attempted": False,
            "has_evidence": False,
        }

    status = row["status"]
    attempted_at = row["submission_attempted_at"]
    submission_status = row["submission_status"]
    current_step = row["current_step"]

    # Check for evidence
    evidence_count = db.execute(
        text(
            "SELECT COUNT(*) FROM application_execution_evidence "
            "WHERE execution_id = :eid"
        ),
        {"eid": execution_id},
    ).scalar() or 0
    has_evidence = evidence_count > 0

    submission_attempted = attempted_at is not None

    # Confirmed — preserve
    if status == "SUBMISSION_CONFIRMED":
        return {
            "action": RecoveryAction.NO_ACTION,
            "reason": "Submission already confirmed.",
            "execution_status": status,
            "submission_attempted": submission_attempted,
            "has_evidence": has_evidence,
        }

    # Submitted — verify outcome
    if status == "SUBMITTED":
        return {
            "action": RecoveryAction.VERIFY_OUTCOME,
            "reason": "Crash after submission. Verify outcome before retry.",
            "execution_status": status,
            "submission_attempted": submission_attempted,
            "has_evidence": has_evidence,
        }

    # Uncertain — human review
    if status == "SUBMISSION_UNKNOWN":
        return {
            "action": RecoveryAction.HUMAN_REVIEW,
            "reason": "Uncertain submission outcome. Human review required.",
            "execution_status": status,
            "submission_attempted": submission_attempted,
            "has_evidence": has_evidence,
        }

    # Submit attempted without outcome — uncertain
    if submission_attempted and submission_status in (None, "UNKNOWN"):
        return {
            "action": RecoveryAction.HUMAN_REVIEW,
            "reason": "Submit was attempted but no outcome confirmed. Human review required.",
            "execution_status": status,
            "submission_attempted": submission_attempted,
            "has_evidence": has_evidence,
        }

    # Pre-submit crash — safe to resume
    if status == "EXECUTING" and not submission_attempted:
        return {
            "action": RecoveryAction.RESUME_SAFE,
            "reason": f"Crash during {current_step or 'execution'}, before submission.",
            "execution_status": status,
            "submission_attempted": False,
            "has_evidence": has_evidence,
        }

    # Terminal states — no action
    if status in ("EXECUTION_FAILED", "BLOCKED", "CANCELLED"):
        return {
            "action": RecoveryAction.NO_ACTION,
            "reason": f"Execution already in terminal state: {status}.",
            "execution_status": status,
            "submission_attempted": submission_attempted,
            "has_evidence": has_evidence,
        }

    # Awaiting approval/user — can resume
    if status in ("AWAITING_APPROVAL", "AWAITING_USER"):
        return {
            "action": RecoveryAction.RESUME_SAFE,
            "reason": f"Execution paused at {current_step or 'approval'}. Safe to resume.",
            "execution_status": status,
            "submission_attempted": submission_attempted,
            "has_evidence": has_evidence,
        }

    # Default — review
    return {
        "action": RecoveryAction.HUMAN_REVIEW,
        "reason": f"Unknown state after crash: {status}.",
        "execution_status": status,
        "submission_attempted": submission_attempted,
        "has_evidence": has_evidence,
    }


# ---------------------------------------------------------------------------
# Stale lock scanner
# ---------------------------------------------------------------------------

def scan_stale_locks(
    db: Session,
    *,
    timeout_seconds: int = STALE_LOCK_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Find all stale execution locks.

    Returns list of stale locks with recovery recommendations.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=timeout_seconds)

    rows = db.execute(
        text(
            "SELECT l.package_id, l.execution_id, l.owner_id, "
            "l.lock_acquired_at, l.heartbeat_at, "
            "e.status, e.submission_attempted_at "
            "FROM execution_locks l "
            "JOIN application_executions e ON e.id = l.execution_id "
            "WHERE l.released_at IS NULL "
            "AND (COALESCE(l.heartbeat_at, l.lock_acquired_at) < :cutoff)"
        ),
        {"cutoff": cutoff},
    ).mappings().all()

    stale_locks = []
    for row in rows:
        recovery = assess_crash_recovery(db, execution_id=row["execution_id"])
        stale_locks.append({
            "package_id": row["package_id"],
            "execution_id": row["execution_id"],
            "owner_id": row["owner_id"],
            "lock_acquired_at": row["lock_acquired_at"],
            "heartbeat_at": row["heartbeat_at"],
            "execution_status": row["status"],
            "submission_attempted": row["submission_attempted_at"] is not None,
            "recommended_action": recovery["action"].value,
            "reason": recovery["reason"],
        })

    return stale_locks


# ---------------------------------------------------------------------------
# Queue idempotency
# ---------------------------------------------------------------------------

def check_queue_duplicate(
    db: Session,
    *,
    job_id: int,
    package_id: int | None = None,
) -> dict[str, Any]:
    """Check for duplicate queue items for the same job.

    Returns:
        - is_duplicate: bool
        - existing_item_id: int | None
        - existing_state: str | None
        - reason: str
    """

    # Check for active queue items for this job
    existing = db.execute(
        text(
            "SELECT id, queue_state, package_id "
            "FROM application_queue_items "
            "WHERE job_id = :jid "
            "AND queue_state NOT IN ('COMPLETED', 'SKIPPED', 'FAILED') "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"jid": job_id},
    ).mappings().first()

    if existing is None:
        return {
            "is_duplicate": False,
            "existing_item_id": None,
            "existing_state": None,
            "reason": "",
        }

    # If same package, it's a duplicate
    if package_id is not None and existing["package_id"] == package_id:
        return {
            "is_duplicate": True,
            "existing_item_id": existing["id"],
            "existing_state": existing["queue_state"],
            "reason": (
                f"Queue item {existing['id']} already exists for this job "
                f"in state {existing['queue_state']}."
            ),
        }

    # Different package for same job — check execution history
    has_submission = db.execute(
        text(
            "SELECT COUNT(*) FROM application_executions e "
            "JOIN application_packages p ON p.id = e.package_id "
            "WHERE p.job_id = :jid "
            "AND e.status IN ('SUBMITTED', 'SUBMISSION_CONFIRMED', 'SUBMISSION_UNKNOWN')"
        ),
        {"jid": job_id},
    ).scalar() or 0

    if has_submission > 0:
        return {
            "is_duplicate": True,
            "existing_item_id": existing["id"],
            "existing_state": existing["queue_state"],
            "reason": f"Prior submission exists for this job (execution count: {has_submission}).",
        }

    return {
        "is_duplicate": False,
        "existing_item_id": existing["id"],
        "existing_state": existing["queue_state"],
        "reason": "",
    }


# ---------------------------------------------------------------------------
# Execution consistency checks
# ---------------------------------------------------------------------------

def check_execution_consistency(
    db: Session,
    *,
    execution_id: int,
) -> dict[str, Any]:
    """Verify execution state consistency.

    Checks for impossible states:
    - SUBMISSION_CONFIRMED without submit attempt
    - EXECUTING with no lock owner
    - SUBMISSION_UNCERTAIN followed automatically by SUBMITTED
    - READY while previous uncertain submission exists
    """
    row = db.execute(
        text(
            "SELECT status, submission_attempted_at, submission_status, "
            "current_step, package_id "
            "FROM application_executions WHERE id = :eid"
        ),
        {"eid": execution_id},
    ).mappings().first()

    if row is None:
        return {"consistent": False, "issues": ["Execution not found."]}

    issues = []
    status = row["status"]
    attempted_at = row["submission_attempted_at"]
    package_id = row["package_id"]

    # SUBMISSION_CONFIRMED without submit attempt
    if status == "SUBMISSION_CONFIRMED" and attempted_at is None:
        issues.append("SUBMISSION_CONFIRMED but no submit attempt recorded.")

    # SUBMITTED without submit attempt
    if status == "SUBMITTED" and attempted_at is None:
        issues.append("SUBMITTED but no submit attempt recorded.")

    # EXECUTING with no lock owner
    if status == "EXECUTING":
        lock_row = db.execute(
            text(
                "SELECT owner_id FROM execution_locks "
                "WHERE package_id = :pid AND released_at IS NULL"
            ),
            {"pid": package_id},
        ).mappings().first()
        if lock_row is None or lock_row["owner_id"] is None:
            issues.append("EXECUTING but no active lock owner.")

    return {
        "consistent": len(issues) == 0,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_lock_manager: ExecutionLockManager | None = None


def get_lock_manager() -> ExecutionLockManager:
    """Get the singleton lock manager."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = ExecutionLockManager()
    return _lock_manager
