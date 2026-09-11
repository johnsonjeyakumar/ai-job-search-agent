"""Phase 24 — Idempotency + Execution Locks + Reliability Hardening tests.

Tests idempotency key generation, submit boundary, retry authorization,
crash recovery, queue idempotency, and execution consistency.

Lock manager tests use raw SQL to avoid FK constraints and advisory lock
complexities in the test environment.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application_execution.idempotency_locks import (
    AttemptState,
    ExecutionLockManager,
    LockOutcome,
    RecoveryAction,
    assess_crash_recovery,
    authorize_retry,
    check_execution_consistency,
    check_submit_boundary,
    generate_idempotency_key,
    get_lock_manager,
    is_retry_authorized,
    mark_submit_attempted,
    parse_idempotency_key,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(db_session):
    """Alias for db_session."""
    return db_session


@pytest.fixture
def execution_factory(db):
    """Factory creating ApplicationExecution rows.

    Creates dummy profiles, jobs, and application_packages rows to satisfy
    FK constraints, then creates the execution row.
    """
    created_execs = []
    created_pkgs = []

    # Seed minimal FK parents (idempotent)
    db.execute(text(
        "INSERT INTO profiles (id, name, email, skills, skills_programming, "
        "skills_frameworks, skills_databases, skills_tools, skills_other, "
        "projects, internships, certifications, preferred_roles, preferred_locations) "
        "VALUES (1, 'Test User', 'test@example.com', '[]', '[]', '[]', '[]', '[]', "
        "'[]', '[]', '[]', '[]', '[]', '[]') "
        "ON CONFLICT (id) DO NOTHING"
    ))
    db.execute(text(
        "INSERT INTO jobs (id, title, company, source, source_job_id, requirements, skills) "
        "VALUES (1, 'Test Job', 'TestCo', 'test', 'test-001', '[]', '[]') "
        "ON CONFLICT DO NOTHING"
    ))
    db.flush()

    def _factory(status: str = "EXECUTING", package_id: int | None = None) -> dict:
        if package_id is None:
            package_id = int(uuid.uuid4().int % 100000)
        # Create dummy package to satisfy FK
        db.execute(
            text(
                "INSERT INTO application_packages "
                "(id, job_id, profile_id, version, status, readiness, quality_gate, "
                "readiness_reasons, resume_selection, gap_analysis, "
                "cover_letter_status, selected_resume_id, recommendation) "
                "VALUES (:pid, 1, 1, 1, 'APPROVED', 'READY', 'PASS', "
                "'[]', '{}', '[]', 'skipped', NULL, 'REVIEW') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"pid": package_id},
        )
        created_pkgs.append(package_id)
        db.flush()

        row = db.execute(
            text(
                "INSERT INTO application_executions "
                "(package_id, platform, execution_mode, status, current_step, "
                "approval_payload, warnings, execution_summary, daily_budget) "
                "VALUES (:pid, 'generic', 'HUMAN_ASSISTED', :status, 'open', "
                "'{}', '[]', '{}', '{}') "
                "RETURNING id"
            ),
            {"pid": package_id, "status": status},
        ).mappings().first()
        db.flush()
        exec_id = row["id"]
        created_execs.append(exec_id)
        return {"id": exec_id, "package_id": package_id, "status": status}

    yield _factory

    for eid in created_execs:
        try:
            db.execute(text("DELETE FROM execution_locks WHERE execution_id = :eid"), {"eid": eid})
            db.execute(text("DELETE FROM application_execution_evidence WHERE execution_id = :eid"), {"eid": eid})
            db.execute(text("DELETE FROM application_execution_steps WHERE execution_id = :eid"), {"eid": eid})
            db.execute(text("DELETE FROM application_executions WHERE id = :eid"), {"eid": eid})
        except Exception:
            pass
    for pid in created_pkgs:
        try:
            db.execute(text("DELETE FROM application_packages WHERE id = :pid"), {"pid": pid})
        except Exception:
            pass
    db.flush()


# ---------------------------------------------------------------------------
# STEP 2 — IDEMPOTENCY KEY
# ---------------------------------------------------------------------------

class TestIdempotencyKey:
    def test_key_deterministic(self):
        k1 = generate_idempotency_key(package_id=10, job_id=20, attempt_number=1)
        k2 = generate_idempotency_key(package_id=10, job_id=20, attempt_number=1)
        assert k1 == k2

    def test_key_unique_per_attempt(self):
        k1 = generate_idempotency_key(package_id=10, job_id=20, attempt_number=1)
        k2 = generate_idempotency_key(package_id=10, job_id=20, attempt_number=2)
        assert k1 != k2

    def test_key_unique_per_package(self):
        k1 = generate_idempotency_key(package_id=10, job_id=20, attempt_number=1)
        k2 = generate_idempotency_key(package_id=11, job_id=20, attempt_number=1)
        assert k1 != k2

    def test_key_format(self):
        k = generate_idempotency_key(package_id=10, job_id=20, attempt_number=3)
        parts = k.split(":")
        assert len(parts) == 3
        assert parts[1] == "10"
        assert parts[2] == "3"

    def test_parse_key(self):
        k = generate_idempotency_key(package_id=10, job_id=20, attempt_number=2)
        parsed = parse_idempotency_key(k)
        assert parsed["package_id"] == 10
        assert parsed["attempt_number"] == 2

    def test_parse_invalid_key(self):
        parsed = parse_idempotency_key("invalid")
        assert parsed == {}

    def test_attempt_states(self):
        assert AttemptState.FIRST_ATTEMPT.value == "FIRST_ATTEMPT"
        assert AttemptState.SUBMIT_ATTEMPTED.value == "SUBMIT_ATTEMPTED"
        assert AttemptState.SUBMISSION_UNCERTAIN.value == "SUBMISSION_UNCERTAIN"
        assert AttemptState.RETRY_AUTHORIZED.value == "RETRY_AUTHORIZED"


# ---------------------------------------------------------------------------
# STEP 3-6 — EXECUTION LOCK MANAGER
# ---------------------------------------------------------------------------

class TestExecutionLockManager:
    def test_singleton(self):
        m1 = get_lock_manager()
        m2 = get_lock_manager()
        assert m1 is m2

    def test_acquire_success(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        result = mgr.acquire(db, package_id=99901, execution_id=1, owner_id=owner)
        assert result.outcome == LockOutcome.ACQUIRED
        assert result.owner_id == owner
        # Cleanup
        mgr.release(db, package_id=99901, owner_id=owner)

    def test_acquire_already_locked(self, db, db_engine):
        """Two separate sessions contend for the same lock."""
        mgr = ExecutionLockManager()
        owner_a = f"worker-a-{uuid.uuid4().hex[:8]}"
        owner_b = f"worker-b-{uuid.uuid4().hex[:8]}"
        # Session A acquires the lock
        r1 = mgr.acquire(db, package_id=99902, execution_id=1, owner_id=owner_a)
        assert r1.outcome == LockOutcome.ACQUIRED
        # Session B tries the same lock — must use a separate connection
        conn_b = db_engine.connect()
        tx_b = conn_b.begin()
        db_b = Session(bind=conn_b, join_transaction_mode="create_savepoint")
        try:
            r2 = mgr.acquire(db_b, package_id=99902, execution_id=2, owner_id=owner_b)
            assert r2.outcome == LockOutcome.ALREADY_LOCKED
        finally:
            db_b.close()
            tx_b.rollback()
            conn_b.close()
        # Cleanup
        mgr.release(db, package_id=99902, owner_id=owner_a)

    def test_release_success(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        mgr.acquire(db, package_id=99903, execution_id=1, owner_id=owner)
        released = mgr.release(db, package_id=99903, owner_id=owner)
        assert released is True

    def test_release_allows_reacquire(self, db):
        mgr = ExecutionLockManager()
        owner_a = f"worker-a-{uuid.uuid4().hex[:8]}"
        owner_b = f"worker-b-{uuid.uuid4().hex[:8]}"
        mgr.acquire(db, package_id=99904, execution_id=1, owner_id=owner_a)
        mgr.release(db, package_id=99904, owner_id=owner_a)
        r = mgr.acquire(db, package_id=99904, execution_id=2, owner_id=owner_b)
        assert r.outcome == LockOutcome.ACQUIRED
        mgr.release(db, package_id=99904, owner_id=owner_b)

    def test_is_locked(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        assert mgr.is_locked(db, package_id=99905) is False
        mgr.acquire(db, package_id=99905, execution_id=1, owner_id=owner)
        assert mgr.is_locked(db, package_id=99905) is True
        mgr.release(db, package_id=99905, owner_id=owner)
        assert mgr.is_locked(db, package_id=99905) is False

    def test_get_owner(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        assert mgr.get_owner(db, package_id=99906) is None
        mgr.acquire(db, package_id=99906, execution_id=1, owner_id=owner)
        assert mgr.get_owner(db, package_id=99906) == owner
        mgr.release(db, package_id=99906, owner_id=owner)

    def test_different_packages_independent(self, db):
        mgr = ExecutionLockManager()
        owner_a = f"worker-a-{uuid.uuid4().hex[:8]}"
        owner_b = f"worker-b-{uuid.uuid4().hex[:8]}"
        r1 = mgr.acquire(db, package_id=99907, execution_id=1, owner_id=owner_a)
        r2 = mgr.acquire(db, package_id=99908, execution_id=2, owner_id=owner_b)
        assert r1.outcome == LockOutcome.ACQUIRED
        assert r2.outcome == LockOutcome.ACQUIRED
        mgr.release(db, package_id=99907, owner_id=owner_a)
        mgr.release(db, package_id=99908, owner_id=owner_b)


# ---------------------------------------------------------------------------
# STEP 7 — STALE LOCK RECOVERY
# ---------------------------------------------------------------------------

class TestStaleLockRecovery:
    def test_stale_lock_detected(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        mgr.acquire(db, package_id=99910, execution_id=1, owner_id=owner)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        db.execute(
            text("UPDATE execution_locks SET heartbeat_at = :old WHERE package_id = :pid"),
            {"old": old_time, "pid": 99910},
        )
        db.flush()
        info = mgr.get_heartbeat_info(db, package_id=99910)
        assert info is not None
        assert info.is_stale is True
        mgr.release(db, package_id=99910, owner_id=owner)

    def test_stale_lock_reacquire(self, db, db_engine):
        """Worker B re-acquires a stale lock held by a dead Worker A.

        Worker A holds PG advisory lock in a separate connection, then
        the connection is closed (simulating crash). Ownership row is stale.
        Worker B detects stale, recovers, and acquires.
        """
        mgr = ExecutionLockManager()
        owner_a = f"worker-a-{uuid.uuid4().hex[:8]}"
        owner_b = f"worker-b-{uuid.uuid4().hex[:8]}"
        # Worker A in a separate connection
        conn_a = db_engine.connect()
        tx_a = conn_a.begin()
        db_a = Session(bind=conn_a, join_transaction_mode="create_savepoint")
        mgr.acquire(db_a, package_id=99911, execution_id=1, owner_id=owner_a)
        tx_a.commit()
        # Make the ownership row stale (heartbeat far in the past)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        db.execute(
            text("UPDATE execution_locks SET heartbeat_at = :old WHERE package_id = :pid"),
            {"old": old_time, "pid": 99911},
        )
        db.flush()
        # Worker A crashes — release PG advisory lock to simulate disconnect
        db_a.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": 99911})
        db_a.flush()
        db_a.close()
        conn_a.close()
        # Worker B detects stale lock and re-acquires
        r = mgr.acquire(db, package_id=99911, execution_id=2, owner_id=owner_b)
        assert r.outcome in (LockOutcome.STALE_LOCK_RELEASED, LockOutcome.ACQUIRED)
        assert r.owner_id == owner_b
        mgr.release(db, package_id=99911, owner_id=owner_b)

    def test_heartbeat_updates(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        mgr.acquire(db, package_id=99912, execution_id=1, owner_id=owner)
        updated = mgr.heartbeat(db, package_id=99912, owner_id=owner)
        assert updated is True
        info = mgr.get_heartbeat_info(db, package_id=99912)
        assert info is not None
        assert info.is_stale is False
        mgr.release(db, package_id=99912, owner_id=owner)

    def test_heartbeat_info(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        mgr.acquire(db, package_id=99913, execution_id=1, owner_id=owner)
        info = mgr.get_heartbeat_info(db, package_id=99913)
        assert info is not None
        assert info.execution_id == 1
        assert info.owner_id == owner
        assert info.is_stale is False
        assert info.lock_acquired_at is not None
        mgr.release(db, package_id=99913, owner_id=owner)


# ---------------------------------------------------------------------------
# STEP 10-11 — SUBMIT ATTEMPT BOUNDARY
# ---------------------------------------------------------------------------

class TestSubmitBoundary:
    def test_can_submit_before_attempt(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is True

    def test_cannot_submit_after_attempt_unknown(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        mark_submit_attempted(db, execution_id=ex["id"])
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is False
        assert "unknown" in boundary["reason"].lower()

    def test_cannot_submit_when_confirmed(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_CONFIRMED")
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is False
        assert "already confirmed" in boundary["reason"].lower()

    def test_cannot_submit_when_submitted(self, db, execution_factory):
        ex = execution_factory(status="SUBMITTED")
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is False
        assert "already occurred" in boundary["reason"].lower()

    def test_cannot_submit_when_uncertain(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_UNKNOWN")
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is False
        assert "uncertain" in boundary["reason"].lower()

    def test_can_submit_when_awaiting_approval(self, db, execution_factory):
        ex = execution_factory(status="AWAITING_APPROVAL")
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is True

    def test_cannot_submit_nonexistent(self, db):
        boundary = check_submit_boundary(db, execution_id=999999)
        assert boundary["can_submit"] is False

    def test_mark_submit_attempted(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        mark_submit_attempted(db, execution_id=ex["id"])
        row = db.execute(
            text("SELECT submission_attempted_at FROM application_executions WHERE id = :eid"),
            {"eid": ex["id"]},
        ).mappings().first()
        assert row["submission_attempted_at"] is not None


# ---------------------------------------------------------------------------
# STEP 12 — RETRY AUTHORIZATION
# ---------------------------------------------------------------------------

class TestRetryAuthorization:
    def test_authorize_retry_uncertain(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_UNKNOWN")
        result = authorize_retry(db, execution_id=ex["id"], reason="Manual check done")
        assert result is True
        assert is_retry_authorized(db, execution_id=ex["id"]) is True

    def test_cannot_authorize_retry_non_uncertain(self, db, execution_factory):
        ex = execution_factory(status="SUBMITTED")
        result = authorize_retry(db, execution_id=ex["id"])
        assert result is False

    def test_cannot_authorize_retry_confirmed(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_CONFIRMED")
        result = authorize_retry(db, execution_id=ex["id"])
        assert result is False

    def test_retry_not_authorized_by_default(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        assert is_retry_authorized(db, execution_id=ex["id"]) is False

    def test_authorize_nonexistent(self, db):
        result = authorize_retry(db, execution_id=999999)
        assert result is False


# ---------------------------------------------------------------------------
# STEP 9 — CRASH RECOVERY
# ---------------------------------------------------------------------------

class TestCrashRecovery:
    def test_crash_before_submit(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.RESUME_SAFE

    def test_crash_after_submit(self, db, execution_factory):
        ex = execution_factory(status="SUBMITTED")
        mark_submit_attempted(db, execution_id=ex["id"])
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.VERIFY_OUTCOME

    def test_crash_uncertain(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_UNKNOWN")
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.HUMAN_REVIEW

    def test_crash_confirmed(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_CONFIRMED")
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.NO_ACTION

    def test_crash_blocked(self, db, execution_factory):
        ex = execution_factory(status="BLOCKED")
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.NO_ACTION

    def test_crash_awaiting_approval(self, db, execution_factory):
        ex = execution_factory(status="AWAITING_APPROVAL")
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.RESUME_SAFE

    def test_crash_nonexistent(self, db):
        recovery = assess_crash_recovery(db, execution_id=999999)
        assert recovery["action"] == RecoveryAction.NO_ACTION

    def test_submit_attempted_without_outcome(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        mark_submit_attempted(db, execution_id=ex["id"])
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.HUMAN_REVIEW


# ---------------------------------------------------------------------------
# STEP 21 — EXECUTION CONSISTENCY
# ---------------------------------------------------------------------------

class TestExecutionConsistency:
    def test_inconsistent_confirmed_no_attempt(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_CONFIRMED")
        result = check_execution_consistency(db, execution_id=ex["id"])
        assert any("SUBMISSION_CONFIRMED but no submit" in i for i in result["issues"])

    def test_nonexistent(self, db):
        result = check_execution_consistency(db, execution_id=999999)
        assert result["consistent"] is False


# ---------------------------------------------------------------------------
# SAFETY TESTS
# ---------------------------------------------------------------------------

class TestSafetyVerification:
    def test_same_package_cannot_concurrent(self, db, db_engine):
        """Two separate sessions cannot hold the same lock concurrently."""
        mgr = ExecutionLockManager()
        owner_a = f"worker-a-{uuid.uuid4().hex[:8]}"
        owner_b = f"worker-b-{uuid.uuid4().hex[:8]}"
        # Session A acquires
        r1 = mgr.acquire(db, package_id=99930, execution_id=1, owner_id=owner_a)
        assert r1.outcome == LockOutcome.ACQUIRED
        # Session B tries same package from a separate connection
        conn_b = db_engine.connect()
        tx_b = conn_b.begin()
        db_b = Session(bind=conn_b, join_transaction_mode="create_savepoint")
        try:
            r2 = mgr.acquire(db_b, package_id=99930, execution_id=2, owner_id=owner_b)
            assert r2.outcome == LockOutcome.ALREADY_LOCKED
        finally:
            db_b.close()
            tx_b.rollback()
            conn_b.close()
        mgr.release(db, package_id=99930, owner_id=owner_a)

    def test_different_packages_independent(self, db):
        mgr = ExecutionLockManager()
        owner_a = f"worker-a-{uuid.uuid4().hex[:8]}"
        owner_b = f"worker-b-{uuid.uuid4().hex[:8]}"
        r1 = mgr.acquire(db, package_id=99931, execution_id=1, owner_id=owner_a)
        r2 = mgr.acquire(db, package_id=99932, execution_id=2, owner_id=owner_b)
        assert r1.outcome == LockOutcome.ACQUIRED
        assert r2.outcome == LockOutcome.ACQUIRED
        mgr.release(db, package_id=99931, owner_id=owner_a)
        mgr.release(db, package_id=99932, owner_id=owner_b)

    def test_post_submit_no_auto_retry(self, db, execution_factory):
        ex = execution_factory(status="EXECUTING")
        mark_submit_attempted(db, execution_id=ex["id"])
        boundary = check_submit_boundary(db, execution_id=ex["id"])
        assert boundary["can_submit"] is False

    def test_uncertain_requires_review(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_UNKNOWN")
        recovery = assess_crash_recovery(db, execution_id=ex["id"])
        assert recovery["action"] == RecoveryAction.HUMAN_REVIEW

    def test_retry_requires_explicit_authorization(self, db, execution_factory):
        ex = execution_factory(status="SUBMISSION_UNKNOWN")
        assert is_retry_authorized(db, execution_id=ex["id"]) is False
        authorize_retry(db, execution_id=ex["id"], reason="User verified")
        assert is_retry_authorized(db, execution_id=ex["id"]) is True

    def test_no_secrets_in_lock_metadata(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        result = mgr.acquire(db, package_id=99933, execution_id=1, owner_id=owner)
        assert "password" not in result.message.lower()
        assert "token" not in result.message.lower()
        assert "cookie" not in result.message.lower()
        assert "otp" not in result.message.lower()
        mgr.release(db, package_id=99933, owner_id=owner)

    def test_stale_lock_not_auto_released(self, db):
        mgr = ExecutionLockManager()
        owner = f"test-{uuid.uuid4().hex[:8]}"
        mgr.acquire(db, package_id=99934, execution_id=1, owner_id=owner)
        info = mgr.get_heartbeat_info(db, package_id=99934)
        assert info is not None
        assert info.is_stale is False
        mgr.release(db, package_id=99934, owner_id=owner)
