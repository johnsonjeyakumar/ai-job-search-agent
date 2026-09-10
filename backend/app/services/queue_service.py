"""Application queue service.

Manages the orchestration queue for approved application packages. The queue
decides *which* packages to process and in *what order*, then delegates to
the existing Phase 7 execution engine.

Queue states are orchestration-only and never conflict with the application
lifecycle statuses tracked in ``application_tracking``.

Priority formula (deterministic, no LLM):
    priority = (match * 0.35) + (opportunity * 0.35) + (quality * 0.15) + (freshness * 0.15)

All weights sum to 1.0 and are documented below.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.application_execution.base import UNSUPPORTED
from app.application_execution.detector import detect_platform
from app.models.application import Application
from app.models.application_execution import ApplicationExecution
from app.models.application_package import ApplicationPackage
from app.models.application_queue import (
    ATTENTION_ASK,
    ATTENTION_AUTO,
    ATTENTION_BLOCK,
    ATTENTION_REVIEW,
    ApplicationQueueItem,
)
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume

# ---------------------------------------------------------------------------
# Priority weights (deterministic, documented, auditable)
# ---------------------------------------------------------------------------
PRIORITY_WEIGHTS = {
    "match": 0.35,
    "opportunity": 0.35,
    "quality": 0.15,
    "freshness": 0.15,
}

# ---------------------------------------------------------------------------
# Queue state transitions (orchestration only)
# ---------------------------------------------------------------------------
_QUEUE_TRANSITIONS: dict[str, frozenset[str]] = {
    "QUEUED": frozenset({"PREPARING", "READY", "NEEDS_INPUT", "REVIEW", "BLOCKED", "SKIPPED"}),
    "PREPARING": frozenset({"READY", "NEEDS_INPUT", "REVIEW", "BLOCKED", "FAILED", "SKIPPED"}),
    "READY": frozenset({"APPROVED", "EXECUTING", "NEEDS_INPUT", "REVIEW", "BLOCKED", "SKIPPED"}),
    "NEEDS_INPUT": frozenset({"READY", "BLOCKED", "SKIPPED"}),
    "REVIEW": frozenset({"READY", "APPROVED", "BLOCKED", "SKIPPED"}),
    "BLOCKED": frozenset({"SKIPPED"}),
    "APPROVED": frozenset({"EXECUTING", "SKIPPED"}),
    "EXECUTING": frozenset({"SUBMITTED", "FAILED", "BLOCKED", "COMPLETED"}),
    "SUBMITTED": frozenset({"COMPLETED", "FAILED"}),
    "FAILED": frozenset({"QUEUED", "SKIPPED"}),
    "SKIPPED": frozenset(),
    "COMPLETED": frozenset(),
}


def _valid_queue_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in _QUEUE_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Priority calculation
# ---------------------------------------------------------------------------

def calculate_priority_score(
    match_score: float | None = None,
    opportunity_score: float | None = None,
    quality_score: float | None = None,
    freshness_score: float | None = None,
) -> float:
    """Deterministic priority score. Higher = process first.

    Formula:
        priority = (match * 0.35) + (opportunity * 0.35)
                 + (quality * 0.15) + (freshness * 0.15)

    Missing scores default to 0. Range: 0.0 – 100.0.
    """
    m = max(0.0, min(100.0, float(match_score or 0)))
    o = max(0.0, min(100.0, float(opportunity_score or 0)))
    q = max(0.0, min(100.0, float(quality_score or 0)))
    f = max(0.0, min(100.0, float(freshness_score or 0)))
    return round(
        m * PRIORITY_WEIGHTS["match"]
        + o * PRIORITY_WEIGHTS["opportunity"]
        + q * PRIORITY_WEIGHTS["quality"]
        + f * PRIORITY_WEIGHTS["freshness"],
        2,
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class QueueNotFoundError(Exception):
    pass


class QueueConflictError(Exception):
    pass


class QueueItemExistsError(Exception):
    pass


class DailyLimitReachedError(Exception):
    pass


class PreflightFailedError(Exception):
    """Preflight checks did not pass; item cannot proceed to execution."""

    def __init__(self, attention: str, reason: str):
        super().__init__(reason)
        self.attention = attention
        self.reason = reason


# ---------------------------------------------------------------------------
# Queue CRUD
# ---------------------------------------------------------------------------

def enqueue(
    db: Session,
    application_id: int,
    package_id: int,
    job_id: int,
) -> ApplicationQueueItem:
    """Add an approved package to the processing queue.

    Raises ``QueueItemExistsError`` if this package is already queued and not
    in a terminal state (COMPLETED/SKIPPED).
    """
    existing = db.scalar(
        select(ApplicationQueueItem).where(
            ApplicationQueueItem.package_id == package_id,
            ApplicationQueueItem.queue_state.notin_(["COMPLETED", "SKIPPED"]),
        )
    )
    if existing is not None:
        raise QueueItemExistsError(
            f"Package {package_id} is already queued (state={existing.queue_state})."
        )

    # Fetch scores for priority calculation.
    job = db.get(Job, job_id)
    package = db.get(ApplicationPackage, package_id)

    match_score = float(package.match_score) if package and package.match_score else None
    opp = package.opportunity_score if package else None
    opportunity_score = float(opp) if opp else None

    # Quality score
    quality_score = None
    if job:
        from app.models.quality import JobQualityScore

        qs = db.scalar(
            select(JobQualityScore)
            .where(JobQualityScore.job_id == job.id)
            .order_by(JobQualityScore.calculated_at.desc())
            .limit(1)
        )
        if qs:
            quality_score = qs.overall_score  # overall quality, not freshness

    # Freshness score (from quality or derived from posted_date)
    freshness_score = None
    if job:
        from app.models.quality import JobQualityScore

        qs = db.scalar(
            select(JobQualityScore)
            .where(JobQualityScore.job_id == job.id)
            .order_by(JobQualityScore.calculated_at.desc())
            .limit(1)
        )
        if qs and qs.freshness_score is not None:
            freshness_score = qs.freshness_score
        elif job.posted_date:
            days_old = (date.today() - job.posted_date).days
            freshness_score = max(0, 100 - days_old * 3)

    # Resume snapshot
    resume_name = None
    if package and package.selected_resume_id:
        resume = db.get(Resume, package.selected_resume_id)
        if resume:
            resume_name = resume.name

    priority = calculate_priority_score(
        match_score, opportunity_score, quality_score, freshness_score
    )

    # Platform detection
    platform = None
    if job:
        detection = detect_platform(
            url=job.url, application_url=job.application_url, source=job.source
        )
        platform = detection.platform

    item = ApplicationQueueItem(
        application_id=application_id,
        package_id=package_id,
        job_id=job_id,
        queue_state="QUEUED",
        priority_score=priority,
        match_score=match_score,
        opportunity_score=opportunity_score,
        quality_score=quality_score,
        freshness_score=freshness_score,
        job_title=job.title if job else None,
        company_name=job.company if job else None,
        platform=platform,
        resume_name=resume_name,
    )
    db.add(item)
    db.flush()
    return item


def get_queue_item(db: Session, item_id: int) -> ApplicationQueueItem | None:
    return db.get(ApplicationQueueItem, item_id)


def list_queue(
    db: Session,
    *,
    state: str | None = None,
    attention: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ApplicationQueueItem]:
    """List queue items with optional filters, ordered by priority desc."""
    stmt = select(ApplicationQueueItem)
    conditions = []
    if state:
        conditions.append(ApplicationQueueItem.queue_state == state)
    if attention:
        conditions.append(ApplicationQueueItem.attention == attention)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(
        ApplicationQueueItem.priority_score.desc(),
        ApplicationQueueItem.position.asc(),
        ApplicationQueueItem.id.asc(),
    ).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def count_queue(
    db: Session,
    *,
    state: str | None = None,
    attention: str | None = None,
) -> int:
    """Count queue items with optional filters (no full row load)."""
    stmt = select(func.count(ApplicationQueueItem.id))
    conditions = []
    if state:
        conditions.append(ApplicationQueueItem.queue_state == state)
    if attention:
        conditions.append(ApplicationQueueItem.attention == attention)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return db.scalar(stmt) or 0


def count_queue_by_state(db: Session) -> dict[str, int]:
    """Count queue items grouped by state."""
    rows = db.execute(
        select(
            ApplicationQueueItem.queue_state,
            func.count(ApplicationQueueItem.id),
        ).group_by(ApplicationQueueItem.queue_state)
    ).all()
    return {row[0]: row[1] for row in rows}


def count_attention_items(db: Session) -> dict[str, int]:
    """Count items needing attention grouped by attention category."""
    rows = db.execute(
        select(
            ApplicationQueueItem.attention,
            func.count(ApplicationQueueItem.id),
        )
        .where(ApplicationQueueItem.attention.isnot(None))
        .where(ApplicationQueueItem.queue_state.notin_(["COMPLETED", "SKIPPED"]))
        .group_by(ApplicationQueueItem.attention)
    ).all()
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def transition_queue_state(
    db: Session,
    item_id: int,
    new_state: str,
    *,
    reason: str | None = None,
    error_message: str | None = None,
) -> ApplicationQueueItem:
    """Move a queue item to a new state."""
    item = db.get(ApplicationQueueItem, item_id)
    if item is None:
        raise QueueNotFoundError(f"Queue item {item_id} not found.")
    if not _valid_queue_transition(item.queue_state, new_state):
        raise QueueConflictError(
            f"Cannot transition {item.queue_state} -> {new_state}."
        )
    item.queue_state = new_state
    if reason:
        item.attention_reason = reason
    if error_message:
        item.error_message = error_message
    if new_state in ("COMPLETED", "SKIPPED", "FAILED"):
        item.processed_at = datetime.now(timezone.utc)
    db.flush()
    return item


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def run_preflight(db: Session, item_id: int) -> ApplicationQueueItem:
    """Run preflight checks on a queue item and classify its attention.

    Returns the updated item with ``attention`` and ``attention_reason`` set.

    Checks:
    1. Job exists
    2. Application exists
    3. Package exists and is APPROVED
    4. Application URL exists
    5. Platform is supported (not UNSUPPORTED)
    6. Required profile information available
    7. Required answers available
    8. Execution policy permits automation
    9. No existing confirmed submission
    10. No unresolved blocking conditions
    11. Job availability recheck (Phase 20)
    12. Deadline validation (Phase 20)
    13. Job identity validation (Phase 20)
    14. Package readiness (Phase 20)
    15. Duplicate detection via Phase 19 (Phase 20)
    """
    from app.application_execution.preflight import (
        JobAvailability,
        run_preflight_checks,
    )
    from app.application_execution.submission_verify import (
        check_duplicate,
        DuplicateVerdict,
    )

    item = db.get(ApplicationQueueItem, item_id)
    if item is None:
        raise QueueNotFoundError(f"Queue item {item_id} not found.")

    reasons: list[str] = []
    attention = ATTENTION_AUTO

    # 1. Job exists
    job = db.get(Job, item.job_id)
    if job is None:
        attention = ATTENTION_BLOCK
        reasons.append("Job not found.")
        _finalize_preflight(db, item, attention, reasons)
        return item

    # 2. Application exists
    application = db.get(Application, item.application_id)
    if application is None:
        attention = ATTENTION_BLOCK
        reasons.append("Application not found.")
        _finalize_preflight(db, item, attention, reasons)
        return item

    # 3. Package exists and is APPROVED
    package = db.get(ApplicationPackage, item.package_id)
    if package is None:
        attention = ATTENTION_BLOCK
        reasons.append("Application package not found.")
        _finalize_preflight(db, item, attention, reasons)
        return item
    if package.status != "APPROVED":
        attention = ATTENTION_REVIEW
        reasons.append(f"Package status is {package.status}, expected APPROVED.")
        _finalize_preflight(db, item, attention, reasons)
        return item

    # 4. Application URL exists
    url = job.application_url or job.url
    if not url:
        attention = ATTENTION_BLOCK
        reasons.append("No application URL available for this job.")
        _finalize_preflight(db, item, attention, reasons)
        return item

    # 5. Platform is supported
    detection = detect_platform(
        url=job.url, application_url=job.application_url, source=job.source
    )
    if detection.platform == "generic" and not job.application_url:
        # generic without application_url may still work, but flag for review
        pass
    platform = detection.platform

    # 6. Profile exists
    profile = db.scalar(select(Profile).order_by(Profile.id).limit(1))
    if profile is None:
        attention = ATTENTION_BLOCK
        reasons.append("No user profile configured.")
        _finalize_preflight(db, item, attention, reasons)
        return item

    # 7. Resume available
    resume = None
    if package.selected_resume_id:
        resume = db.get(Resume, package.selected_resume_id)
    if resume is None:
        attention = ATTENTION_ASK
        reasons.append("No resume selected for this package.")

    # 8. Check for existing confirmed submission
    existing_execution = db.scalar(
        select(ApplicationExecution).where(
            ApplicationExecution.package_id == item.package_id,
            ApplicationExecution.status.in_([
                "SUBMITTED", "SUBMISSION_CONFIRMED", "EXECUTING",
            ]),
        )
    )
    if existing_execution is not None:
        if existing_execution.status in ("SUBMITTED", "SUBMISSION_CONFIRMED"):
            attention = ATTENTION_BLOCK
            reasons.append(
                f"Package already has a {existing_execution.status} execution "
                f"(id={existing_execution.id})."
            )
            _finalize_preflight(db, item, attention, reasons)
            return item
        if existing_execution.status == "EXECUTING":
            attention = ATTENTION_BLOCK
            reasons.append(
                f"Package is currently being executed (execution id={existing_execution.id})."
            )
            _finalize_preflight(db, item, attention, reasons)
            return item

    # 9. Check for unresolved unknown questions
    from app.models.application_package import ApplicationAnswer

    invalid_answers = list(
        db.scalars(
            select(ApplicationAnswer)
            .where(ApplicationAnswer.package_id == item.package_id)
            .where(ApplicationAnswer.validation_status == "INVALID")
        )
    )
    if invalid_answers:
        attention = ATTENTION_ASK
        reasons.append(
            f"{len(invalid_answers)} answer(s) need user input."
        )

    # 10. Check execution mode
    prefs = db.scalar(select(Preferences).order_by(Preferences.id).limit(1))
    from app.application_execution.adapters import get_adapter

    adapter = get_adapter(platform)
    policy = adapter.policy(
        dict(getattr(prefs, "platform_policies", None) or {}) if prefs else {}
    )
    if policy.mode == UNSUPPORTED:
        attention = ATTENTION_BLOCK
        reasons.append(f"Platform {platform} does not support automation.")

    # Update platform on the item
    item.platform = platform

    # ── Phase 20: Extended preflight checks ──────────────────────────────

    # 11. Job availability recheck (use existing freshness + job state)
    from app.services.freshness_service import classify as freshness_classify
    freshness = freshness_classify(job.posted_date)
    from app.application_execution.preflight import availability_from_freshness
    job_availability = availability_from_freshness(freshness.status)

    # 12. Duplicate detection via Phase 19
    existing_apps = []
    prev_app = db.scalar(
        select(Application)
        .where(Application.job_id == job.id)
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if prev_app is not None:
        existing_apps.append({
            "id": prev_app.id,
            "job_id": prev_app.job_id,
            "lifecycle_status": prev_app.lifecycle_status,
        })

    existing_execs = []
    prior_exec = db.scalar(
        select(ApplicationExecution)
        .where(ApplicationExecution.package_id == item.package_id)
        .where(ApplicationExecution.status.in_(["SUBMITTED", "SUBMISSION_CONFIRMED", "SUBMISSION_UNKNOWN"]))
        .order_by(ApplicationExecution.id.desc())
        .limit(1)
    )
    if prior_exec is not None:
        existing_execs.append({"id": prior_exec.id, "status": prior_exec.status})

    dup_result = check_duplicate(
        job_id=job.id,
        existing_applications=existing_apps,
        existing_executions=existing_execs,
    )
    dup_status = dup_result.verdict.value

    # 13. Run composite preflight checks
    profile_data = {}
    if profile:
        profile_data = {
            "name": getattr(profile, "name", None),
            "email": getattr(profile, "email", None),
            "phone": getattr(profile, "phone", None),
        }

    result = run_preflight_checks(
        job_id=job.id,
        job_availability=job_availability,
        job_company=job.company,
        job_title=job.title,
        job_url=job.url,
        original_company=item.company_name,
        original_title=item.job_title,
        original_url=None,
        application_deadline=None,
        package_id=item.package_id,
        package_status=package.status,
        quality_gate=package.quality_gate,
        selected_resume_id=package.selected_resume_id,
        resume_exists=(resume is not None),
        readiness=package.readiness,
        duplicate_status=dup_status,
        profile_data=profile_data if profile_data else None,
        application_url=url,
    )

    # Merge Phase 20 reason codes into existing reasons
    for code in result.reason_codes:
        reasons.append(code)

    # If Phase 20 determined non-eligible, override attention
    if not result.eligible and attention == ATTENTION_AUTO:
        if result.has_blockers:
            attention = ATTENTION_BLOCK
        elif result.needs_review:
            attention = ATTENTION_REVIEW

    _finalize_preflight(db, item, attention, reasons)
    return item


def _finalize_preflight(
    db: Session,
    item: ApplicationQueueItem,
    attention: str,
    reasons: list[str],
) -> None:
    item.attention = attention
    item.attention_reason = "; ".join(reasons) if reasons else None
    if attention == ATTENTION_AUTO:
        item.queue_state = "READY"
    elif attention == ATTENTION_ASK:
        item.queue_state = "NEEDS_INPUT"
    elif attention == ATTENTION_REVIEW:
        item.queue_state = "REVIEW"
    elif attention == ATTENTION_BLOCK:
        item.queue_state = "BLOCKED"
    db.flush()


# ---------------------------------------------------------------------------
# Resolve / Skip
# ---------------------------------------------------------------------------

def resolve_item(
    db: Session,
    item_id: int,
    resolution_data: dict,
) -> ApplicationQueueItem:
    """Resolve a NEEDS_INPUT item with user-provided data and re-run preflight."""
    item = db.get(ApplicationQueueItem, item_id)
    if item is None:
        raise QueueNotFoundError(f"Queue item {item_id} not found.")
    if item.queue_state != "NEEDS_INPUT":
        raise QueueConflictError(
            f"Item {item_id} is in state {item.queue_state}, expected NEEDS_INPUT."
        )
    item.resolution_data = resolution_data
    item.queue_state = "QUEUED"
    item.attention = None
    item.attention_reason = None
    db.flush()
    return run_preflight(db, item_id)


def skip_item(
    db: Session,
    item_id: int,
    reason: str | None = None,
) -> ApplicationQueueItem:
    """Skip a queue item."""
    item = transition_queue_state(db, item_id, "SKIPPED", reason=reason)
    if reason:
        item.skip_reason = reason
    db.flush()
    return item


# ---------------------------------------------------------------------------
# Daily limits
# ---------------------------------------------------------------------------

def get_daily_submission_count(db: Session) -> int:
    """Count confirmed submissions today."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    count = db.scalar(
        select(func.count(ApplicationExecution.id)).where(
            ApplicationExecution.status.in_(["SUBMITTED", "SUBMISSION_CONFIRMED"]),
            ApplicationExecution.completed_at >= today_start,
        )
    )
    return count or 0


def get_daily_limits(db: Session) -> dict:
    """Get daily target and maximum from preferences."""
    prefs = db.scalar(select(Preferences).order_by(Preferences.id).limit(1))
    return {
        "target": getattr(prefs, "daily_application_target", None) or 5,
        "maximum": getattr(prefs, "daily_application_maximum", None) or 10,
    }


def check_daily_limit(db: Session) -> bool:
    """Return True if daily maximum has been reached."""
    limits = get_daily_limits(db)
    count = get_daily_submission_count(db)
    return count >= limits["maximum"]


def get_active_execution_count(db: Session) -> int:
    """Count currently executing items."""
    count = db.scalar(
        select(func.count(ApplicationQueueItem.id)).where(
            ApplicationQueueItem.queue_state == "EXECUTING"
        )
    )
    return count or 0


def get_max_concurrent(db: Session) -> int:
    """Get max concurrent executions from preferences (default 1).

    This is separate from daily_application_target and daily_maximum.
    """
    prefs = db.scalar(select(Preferences).order_by(Preferences.id).limit(1))
    return getattr(prefs, "max_concurrent_executions", None) or 1
