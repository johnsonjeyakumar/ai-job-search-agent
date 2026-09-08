"""Autopilot service.

Manages autopilot runs that batch-process queued application items through the
existing Phase 7 execution engine. The autopilot is the "automatic job
application agent" — it picks up items in priority order, runs preflight,
classifies attention, and delegates to the executor for AUTO items.

Safety:
- Respects daily submission limits (Preferences.daily_application_target/maximum)
- Respects concurrency limits (max 1 simultaneous execution by default)
- Every item must resolve to: AUTO / ASK / REVIEW / BLOCK
- Runs are interruptible (pause/resume/stop)
- Each item goes through: preflight -> attention classification -> execution
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application_execution.executor import run_execution
from app.models.application_package import ApplicationPackage
from app.models.application_queue import (
    ATTENTION_AUTO,
    ApplicationQueueItem,
    AutopilotRun,
)
from app.services import queue_service

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AutopilotConflictError(Exception):
    pass


class AutopilotNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

def start_autopilot(
    db: Session,
    *,
    target_count: int = 5,
) -> AutopilotRun:
    """Start a new autopilot run.

    Picks up ``target_count`` queued items in priority order and processes
    them sequentially. Only one run can be active at a time.

    Returns the newly created AutopilotRun.
    """
    target_count = max(1, min(50, target_count))

    active = db.scalar(
        select(AutopilotRun).where(
            AutopilotRun.status.in_(["RUNNING", "PAUSED"])
        )
    )
    if active is not None:
        raise AutopilotConflictError(
            f"Another autopilot run (id={active.id}) is already active "
            f"with status {active.status}."
        )

    run = AutopilotRun(
        status="RUNNING",
        target_count=target_count,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    return run


def pause_autopilot(db: Session, run_id: int) -> AutopilotRun:
    """Pause an active autopilot run."""
    run = db.get(AutopilotRun, run_id)
    if run is None:
        raise AutopilotNotFoundError(f"Autopilot run {run_id} not found.")
    if run.status != "RUNNING":
        raise AutopilotConflictError(
            f"Run {run_id} is in status {run.status}, expected RUNNING."
        )
    run.status = "PAUSED"
    db.flush()
    return run


def resume_autopilot(db: Session, run_id: int) -> AutopilotRun:
    """Resume a paused autopilot run."""
    run = db.get(AutopilotRun, run_id)
    if run is None:
        raise AutopilotNotFoundError(f"Autopilot run {run_id} not found.")
    if run.status != "PAUSED":
        raise AutopilotConflictError(
            f"Run {run_id} is in status {run.status}, expected PAUSED."
        )
    run.status = "RUNNING"
    db.flush()
    return run


def stop_autopilot(
    db: Session,
    run_id: int,
    *,
    reason: str | None = None,
) -> AutopilotRun:
    """Stop an autopilot run."""
    run = db.get(AutopilotRun, run_id)
    if run is None:
        raise AutopilotNotFoundError(f"Autopilot run {run_id} not found.")
    run.status = "COMPLETED"
    run.ended_at = datetime.now(timezone.utc)
    if reason:
        run.error_message = reason
    db.flush()
    return run


def get_autopilot_status(db: Session) -> AutopilotRun | None:
    """Get the most recent autopilot run."""
    return db.scalar(
        select(AutopilotRun).order_by(AutopilotRun.id.desc()).limit(1)
    )


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_next_item(
    db: Session,
    run: AutopilotRun,
    *,
    headless: bool = True,
) -> ApplicationQueueItem | None:
    """Pick up and process the next queued item.

    Returns the processed item, or None if there are no more items to process.

    ``processed_count`` means "items attempted by autopilot" (includes items
    that fail preflight). This ensures the autopilot stops after attempting
    the target number of items, regardless of outcome.

    Processing steps:
    1. Find next QUEUED item in priority order
    2. Run preflight (sets attention category)
    3. If AUTO -> execute via Phase 7 engine
    4. If ASK/REVIEW/BLOCK -> leave in attention state
    5. Update run counters
    """
    # Check concurrency limit.
    max_concurrent = queue_service.get_max_concurrent(db)
    active_count = queue_service.get_active_execution_count(db)
    if active_count >= max_concurrent:
        return None

    # Check daily limit.
    if queue_service.check_daily_limit(db):
        run.status = "COMPLETED"
        run.ended_at = datetime.now(timezone.utc)
        db.flush()
        return None

    # Check target reached.
    if run.processed_count >= run.target_count:
        run.status = "COMPLETED"
        run.ended_at = datetime.now(timezone.utc)
        db.flush()
        return None

    # Find next queued item.
    item = db.scalar(
        select(ApplicationQueueItem)
        .where(ApplicationQueueItem.queue_state == "QUEUED")
        .order_by(
            ApplicationQueueItem.priority_score.desc(),
            ApplicationQueueItem.position.asc(),
            ApplicationQueueItem.id.asc(),
        )
        .limit(1)
    )
    if item is None:
        run.status = "COMPLETED"
        run.ended_at = datetime.now(timezone.utc)
        db.flush()
        return None

    # Link to run.
    item.autopilot_run_id = run.id
    run.current_queue_item_id = item.id
    run.processed_count += 1
    db.flush()

    try:
        # Run preflight.
        item = queue_service.run_preflight(db, item.id)
        db.flush()

        if item.attention == ATTENTION_AUTO:
            # Execute via Phase 7 engine.
            queue_service.transition_queue_state(db, item.id, "EXECUTING")
            package = db.get(ApplicationPackage, item.package_id)
            if package is None:
                item.queue_state = "FAILED"
                item.error_message = "Package not found during execution."
                run.failed_count += 1
                db.flush()
            else:
                try:
                    execution = run_execution(
                        db, package, headless=headless, driver_name="auto"
                    )
                    item.execution_id = execution.id
                    if execution.status == "EXECUTING":
                        item.queue_state = "SUBMITTED"
                        run.submitted_count += 1
                    elif execution.status == "AWAITING_APPROVAL":
                        item.queue_state = "REVIEW"
                        item.attention = "REVIEW"
                        item.attention_reason = f"Awaiting approval: {execution.current_step}"
                        run.review_count += 1
                    elif execution.status == "AWAITING_USER":
                        item.queue_state = "NEEDS_INPUT"
                        item.attention = "ASK"
                        item.attention_reason = f"Awaiting user input: {execution.current_step}"
                        run.input_count += 1
                    elif execution.status == "BLOCKED":
                        item.queue_state = "BLOCKED"
                        item.error_message = f"Blocked: {execution.current_step}"
                        run.blocked_count += 1
                    else:
                        item.queue_state = "COMPLETED"
                except Exception as e:
                    item.queue_state = "FAILED"
                    item.error_message = str(e)[:500]
                    run.failed_count += 1
                db.flush()
        elif item.attention in ("ASK", "REVIEW", "BLOCK"):
            run.review_count += 1
        else:
            run.review_count += 1

    except Exception as e:
        item.queue_state = "FAILED"
        item.error_message = str(e)[:500]
        run.failed_count += 1
        db.flush()

    db.flush()
    return item


def get_pending_items_count(db: Session) -> int:
    """Count items waiting in queue."""
    count = db.scalar(
        select(func.count(ApplicationQueueItem.id)).where(
            ApplicationQueueItem.queue_state.in_(["QUEUED", "NEEDS_INPUT", "REVIEW"])
        )
    )
    return count or 0


def get_attention_items_count(db: Session) -> dict[str, int]:
    """Count items needing attention by category."""
    return queue_service.count_attention_items(db)


def queue_stats(db: Session) -> dict:
    """Get overall queue statistics for the dashboard."""
    state_counts = queue_service.count_queue_by_state(db)
    attention_counts = queue_service.count_attention_items(db)
    limits = queue_service.get_daily_limits(db)
    daily_submitted = queue_service.get_daily_submission_count(db)
    pending = get_pending_items_count(db)
    active_execution = queue_service.get_active_execution_count(db)
    return {
        "state_counts": state_counts,
        "attention_counts": attention_counts,
        "pending_count": pending,
        "active_execution_count": active_execution,
        "daily_submitted": daily_submitted,
        "daily_target": limits["target"],
        "daily_maximum": limits["maximum"],
    }
