"""Application lifecycle + tracking service (Phase 8).

The single place that moves an :class:`~app.models.application.Application`
through the controlled state machine, appends immutable history, and manages
follow-ups / responses / interviews / offers. ``source`` on every event
declares who caused the change (USER / SYSTEM / EXECUTION / ...).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application_tracking import status as app_status
from app.application_tracking.events import (
    record_application_event,
)
from app.models.application import Application, FollowUp
from app.models.application_package import ApplicationPackage
from app.models.application_tracking import (
    FOLLOW_UP_STATUSES,
    LEGACY_STATUS_MAP,
    RESPONSE_CATEGORIES,
    TRACKING_STATUSES,
    ApplicationResponse,
    InterviewRecord,
    OfferRecord,
)
from app.models.profile import Profile
from app.models.resume import Resume


class TrackingError(Exception):
    """Base error with an HTTP-ish status for the API boundary."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# Canonical forward paths to INTERVIEW / OFFER when the target is not a direct
# edge (e.g. SUBMITTED has no INTERVIEW/OFFER edge; a real response logically
# passes through RESPONSE_RECEIVED first). Each hop is recorded as one event.
_RESPONSE_TARGET_PATHS: dict[tuple[str, str], tuple[str, ...]] = {
    ("SUBMITTED", "INTERVIEW"): ("RESPONSE_RECEIVED", "INTERVIEW"),
    ("SUBMITTED", "OFFER"): ("RESPONSE_RECEIVED", "OFFER"),
    ("SUBMISSION_CONFIRMED", "INTERVIEW"): ("RESPONSE_RECEIVED", "INTERVIEW"),
    ("SUBMISSION_CONFIRMED", "OFFER"): ("RESPONSE_RECEIVED", "OFFER"),
    ("RESPONSE_RECEIVED", "INTERVIEW"): ("INTERVIEW",),
    ("RESPONSE_RECEIVED", "OFFER"): ("OFFER",),
    ("INTERVIEW", "OFFER"): ("OFFER",),
}


def _first_profile_id(db: Session) -> int | None:
    profile = db.scalar(select(Profile.id).order_by(Profile.id).limit(1))
    return profile if profile is None else int(profile)


def application_for_job(db: Session, job_id: int) -> Application | None:
    return db.scalar(
        select(Application)
        .where(Application.job_id == job_id)
        .order_by(Application.id.desc())
        .limit(1)
    )


def ensure_application_for_job(
    db: Session,
    job_id: int,
    *,
    initial_status: str = "SHORTLISTED",
    source: str = "USER",
    notes: str | None = None,
    resume: Resume | None = None,
) -> Application:
    """Get-or-create the tracked application row for a job.

    On creation it records an ``APPLICATION_CREATED`` event plus a milestone
    event for the initial status (e.g. ``SHORTLISTED``).
    """
    existing = application_for_job(db, job_id)
    if existing is not None:
        return existing

    app = Application(
        job_id=job_id,
        profile_id=_first_profile_id(db),
        resume_id=resume.id if resume is not None else None,
        status=LEGACY_STATUS_MAP.get(initial_status, "saved"),
        lifecycle_status=initial_status,
        resume_name=resume.name if resume is not None else None,
        resume_version=resume.version if resume is not None else None,
        notes=notes,
    )
    db.add(app)
    db.flush()

    record_application_event(
        db,
        app.id,
        "APPLICATION_CREATED",
        source=source,
        previous_status=None,
        new_status=initial_status,
        notes=notes,
        metadata={"job_id": job_id},
    )
    if initial_status != "DISCOVERED":
        record_application_event(
            db,
            app.id,
            app_status.default_event_for_status(initial_status),
            source=source,
            previous_status="DISCOVERED",
            new_status=initial_status,
            notes=notes,
        )
    db.flush()
    return app


def move_lifecycle(
    db: Session,
    application: Application,
    target: str,
    *,
    source: str = "USER",
    notes: str | None = None,
    override: bool = False,
    event_type: str | None = None,
    event_timestamp: datetime | None = None,
    metadata: dict | None = None,
    _record_new_submission_follow_up: bool = True,
) -> Application:
    """Apply one lifecycle transition (appends one immutable event)."""
    current = application.lifecycle_status
    app_status.validate_target_status(target)
    if current == target:
        return application
    if not (override or app_status.can_transition(current, target)):
        raise TrackingError(
            f"Illegal transition {current} -> {target}.",
            status_code=409,
        )

    previous = current
    application.lifecycle_status = target
    application.status = LEGACY_STATUS_MAP.get(target, "saved")
    event_type = event_type or (
        "STATUS_CORRECTED"
        if override
        else app_status.default_event_for_status(target)
    )
    record_application_event(
        db,
        application.id,
        event_type,
        source=source,
        previous_status=previous,
        new_status=target,
        notes=notes,
        metadata=metadata,
        event_timestamp=event_timestamp,
    )
    db.flush()

    # A newly submitted application gets a follow-up scheduled centrally.
    if (
        _record_new_submission_follow_up
        and target in ("SUBMITTED", "SUBMISSION_CONFIRMED")
        and previous not in app_status.SUBMITTED_STATUSES
    ):
        create_follow_up(db, application, source=source)
    return application


def set_status_manual(
    db: Session,
    application_id: int,
    target: str,
    *,
    source: str = "USER",
    notes: str | None = None,
    override: bool = False,
) -> Application:
    """API-facing controlled status update (PATCH /tracking/applications/{id}/status)."""
    application = db.get(Application, application_id)
    if application is None:
        raise TrackingError("Application not found.", 404)
    app_status.validate_target_status(target)
    if not override and not app_status.can_transition(
        application.lifecycle_status, target
    ):
        raise TrackingError(
            f"Illegal transition {application.lifecycle_status} -> {target}. "
            "Use override to record a manual correction (STATUS_CORRECTED).",
            409,
        )
    return move_lifecycle(
        db,
        application,
        target,
        source=source,
        notes=notes,
        override=override,
    )


def add_note(
    db: Session,
    application: Application,
    text: str,
    *,
    source: str = "USER",
) -> Application:
    notes = (application.notes or "").strip()
    application.notes = f"{notes}\n{text}".strip() if notes else text.strip()
    record_application_event(
        db,
        application.id,
        "NOTE_ADDED",
        source=source,
        previous_status=application.lifecycle_status,
        new_status=application.lifecycle_status,
        notes=text.strip(),
    )
    db.flush()
    return application


# ---------------------------------------------------------------------------
# Responses / interviews / offers
# ---------------------------------------------------------------------------


def _move_toward_target(
    db: Session,
    application: Application,
    *,
    target: str,
    source: str,
    notes: str | None,
    event_type: str,
    metadata: dict | None = None,
) -> None:
    """Move the application to ``target`` where reachable.

    Walks the canonical response chain when no direct edge exists (a response
    recorded from SUBMITTED passes through RESPONSE_RECEIVED first). When the
    target is genuinely unreachable without an override (e.g. an interview on
    an OFFER app) the outcome is still recorded as an immutable history event
    with the status unchanged — never silent, never a fake change.
    """
    current = application.lifecycle_status
    if current == target:
        return
    if app_status.can_transition(current, target):
        move_lifecycle(
            db,
            application,
            target,
            source=source,
            notes=notes,
            _record_new_submission_follow_up=False,
        )
        return
    path = _RESPONSE_TARGET_PATHS.get((current, target))
    if path is not None:
        for hop in path:
            move_lifecycle(
                db,
                application,
                hop,
                source=source,
                notes=notes,
                _record_new_submission_follow_up=False,
            )
        return
    record_application_event(
        db,
        application.id,
        event_type,
        source=source,
        previous_status=current,
        new_status=current,
        notes=notes,
        metadata=metadata,
    )


def record_response(
    db: Session,
    application: Application,
    *,
    category: str,
    received_at: date,
    notes: str | None = None,
    source: str = "USER",
) -> ApplicationResponse:
    category = category.upper()
    if category not in RESPONSE_CATEGORIES:
        raise TrackingError(f"Invalid response category: {category!r}", 422)

    row = ApplicationResponse(
        application_id=application.id,
        category=category,
        received_at=received_at,
        notes=notes,
    )
    db.add(row)
    db.flush()

    target_map = {
        "REJECTED": "REJECTED",
        "OFFER": "OFFER",
        "INTERVIEW": "INTERVIEW",
    }
    target = target_map.get(category)
    if target is not None:
        _move_toward_target(
            db,
            application,
            target=target,
            source=source,
            notes=notes,
            event_type=app_status.default_event_for_status(target),
            metadata={"response_category": category},
        )
    elif app_status.can_transition(
        application.lifecycle_status, "RESPONSE_RECEIVED"
    ):
        move_lifecycle(
            db,
            application,
            "RESPONSE_RECEIVED",
            source=source,
            notes=notes,
            _record_new_submission_follow_up=False,
        )
    else:
        # Status stays put (e.g. already INTERVIEW/OFFER); still record the
        # response transparently as history.
        record_application_event(
            db,
            application.id,
            "RESPONSE_RECEIVED",
            source=source,
            previous_status=application.lifecycle_status,
            new_status=application.lifecycle_status,
            notes=notes,
            metadata={"response_category": category},
        )
    db.flush()
    return row


def record_interview(
    db: Session,
    application: Application,
    *,
    interview_date: date,
    interview_type: str = "OTHER",
    round_number: int = 1,
    status: str = "SCHEDULED",
    notes: str | None = None,
    source: str = "USER",
) -> InterviewRecord:
    row = InterviewRecord(
        application_id=application.id,
        interview_date=interview_date,
        interview_type=interview_type.upper(),
        round=round_number,
        status=status.upper(),
        notes=notes,
    )
    db.add(row)
    db.flush()
    _move_toward_target(
        db,
        application,
        target="INTERVIEW",
        source=source,
        notes=notes,
        event_type="INTERVIEW_SCHEDULED",
        metadata={"interview_type": interview_type, "round": round_number},
    )
    db.flush()
    # Deterministic thank-you follow-up for this specific interview record.
    schedule_interview_follow_up(
        db,
        application,
        row,
        source=source if source in ("SYSTEM", "EXECUTION") else "USER",
    )
    db.flush()
    return row


def record_offer(
    db: Session,
    application: Application,
    *,
    offer_date: date,
    status: str = "RECEIVED",
    notes: str | None = None,
    source: str = "USER",
) -> OfferRecord:
    row = OfferRecord(
        application_id=application.id,
        offer_date=offer_date,
        status=status.upper(),
        notes=notes,
    )
    db.add(row)
    db.flush()
    _move_toward_target(
        db,
        application,
        target="OFFER",
        source=source,
        notes=notes,
        event_type="OFFER_RECEIVED",
    )
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------


def submit_date(application: Application) -> date | None:
    return application.applied_date or (
        application.created_at.date()
        if application.created_at is not None
        else None
    )


def follow_up_interval_days(db: Session) -> int:
    from app.models.preferences import Preferences

    prefs = db.scalar(select(Preferences).order_by(Preferences.id).limit(1))
    return int(prefs.follow_up_interval_days) if prefs is not None else 7


def interview_follow_up_days(db: Session) -> int:
    from app.models.preferences import Preferences

    prefs = db.scalar(select(Preferences).order_by(Preferences.id).limit(1))
    return int(prefs.interview_follow_up_days) if prefs is not None else 1


# Lifecycle statuses for which NO follow-up is ever scheduled (they declare the
# application ended). OFFER included: an offer stops further active follow-ups.
_NO_FOLLOW_UP_STATUSES = frozenset(
    {"REJECTED", "WITHDRAWN", "EXPIRED", "CANCELLED", "OFFER"}
)


def create_follow_up(
    db: Session,
    application: Application,
    *,
    source: str = "SYSTEM",
    scheduled_date: date | None = None,
    reason: str = "SUBMISSION_FOLLOW_UP",
    priority: str = "MEDIUM",
    trigger_status: str | None = None,
    trigger_key: str | None = None,
    allow_extra_for_application: bool = False,
) -> FollowUp | None:
    """Create one deterministic follow-up (idempotent per trigger key).

    Skipped when the application is in a no-follow-up lifecycle status
    (rejected / withdrawn / expired / cancelled / offer) or already has a
    response. A submission follow-up is deduped per trigger key, so repeated
    hits of the same trigger never create duplicates. Distinct interviews are
    allowed their own thank-you follow-up (``allow_extra_for_application``).
    """
    reason = (reason or "SUBMISSION_FOLLOW_UP").upper()
    priority = (priority or "MEDIUM").upper()
    if reason not in ("SUBMISSION_FOLLOW_UP", "INTERVIEW_THANK_YOU"):
        raise TrackingError(f"Invalid follow-up reason: {reason!r}", 422)
    if priority not in ("HIGH", "MEDIUM", "LOW"):
        raise TrackingError(f"Invalid follow-up priority: {priority!r}", 422)
    if application.lifecycle_status in _NO_FOLLOW_UP_STATUSES:
        return None
    existing_response = db.scalar(
        select(ApplicationResponse.id).where(
            ApplicationResponse.application_id == application.id
        ).limit(1)
    )
    if existing_response is not None:
        return None

    trigger_status = trigger_status or application.lifecycle_status
    trigger_key = trigger_key or (
        f"app:{application.id}:{reason}:{trigger_status}"
    )
    existing_by_key = db.scalar(
        select(FollowUp.id).where(
            FollowUp.application_id == application.id,
            FollowUp.trigger_key == trigger_key,
        ).limit(1)
    )
    if existing_by_key is not None:
        return None
    if not allow_extra_for_application:
        any_follow_up = db.scalar(
            select(FollowUp.id).where(
                FollowUp.application_id == application.id
            ).limit(1)
        )
        if any_follow_up is not None:
            return None

    base_date = submit_date(application)
    scheduled = scheduled_date or (
        (base_date + timedelta(days=follow_up_interval_days(db)))
        if base_date is not None
        else date.today()
    )
    label = reason.replace("_", " ").title()
    if reason == "SUBMISSION_FOLLOW_UP":
        note = (
            f"Follow up {follow_up_interval_days(db)} days after submission."
            if scheduled_date is None
            else f"Follow up {submit_date(application)}."
        )
    else:
        note = (
            "Follow up after the interview"
            if scheduled_date is None
            else f"Follow up on {scheduled.isoformat()}."
        )
    row = FollowUp(
        application_id=application.id,
        action_type="follow_up",
        priority=priority,
        reason=reason,
        trigger_status=trigger_status,
        trigger_key=trigger_key,
        scheduled_date=scheduled,
        reminder_date=scheduled,
        status="PENDING",
        notes=note,
    )
    db.add(row)
    db.flush()
    record_application_event(
        db,
        application.id,
        "FOLLOW_UP_SCHEDULED",
        source=source,
        previous_status=application.lifecycle_status,
        new_status=application.lifecycle_status,
        notes=f"{label} scheduled for {scheduled.isoformat()}.",
        metadata={
            "priority": priority,
            "reason": reason,
            "trigger_status": trigger_status,
            "trigger_key": trigger_key,
        },
    )
    db.flush()
    return row


def schedule_interview_follow_up(
    db: Session,
    application: Application,
    interview_record: InterviewRecord,
    *,
    source: str = "SYSTEM",
) -> FollowUp | None:
    """Deterministic thank-you follow-up after an interview is scheduled.

    One follow-up per interview record (``trigger_key`` embeds the record id),
    offset by the user-configurable ``interview_follow_up_days``.
    """
    if application.lifecycle_status in _NO_FOLLOW_UP_STATUSES:
        return None
    base = interview_record.interview_date
    scheduled = base + timedelta(days=interview_follow_up_days(db))
    return create_follow_up(
        db,
        application,
        source=source,
        scheduled_date=scheduled,
        reason="INTERVIEW_THANK_YOU",
        priority="HIGH",
        trigger_status="INTERVIEW",
        trigger_key=f"app:{application.id}:INTERVIEW_THANK_YOU:{interview_record.id}",
        allow_extra_for_application=True,
    )


def follow_up_state(follow_up: FollowUp, today: date | None = None) -> str:
    """Effective state: PENDING | DUE | COMPLETED | CANCELLED.

    ``DUE`` is derived: not terminal and scheduled_date <= today.
    """
    stored = (follow_up.status or "PENDING").upper()
    if stored in ("COMPLETED", "CANCELLED"):
        return stored
    today = today or date.today()
    if follow_up.scheduled_date is not None and follow_up.scheduled_date <= today:
        return "DUE"
    return "PENDING"


def follow_up_lifecycle_state(
    follow_up: FollowUp,
    *,
    rescheduled: bool = False,
    today: date | None = None,
) -> str:
    """Full Phase 9 follow-up lifecycle state (SCHEDULED/DUE/OVERDUE/
    RESCHEDULED/COMPLETED/CANCELLED/SKIPPED), fully derived and deterministic.

    Stored terminal status wins; then OVERDUE/DUE (active, past/equal date);
    then RESCHEDULED for active future follow-ups with a reschedule event;
    then SCHEDULED (a plain future/undated active follow-up).
    """
    stored = (follow_up.status or "PENDING").upper()
    if stored == "COMPLETED":
        return "COMPLETED"
    if stored == "CANCELLED":
        return "CANCELLED"
    if stored == "SKIPPED":
        return "SKIPPED"
    today = today or date.today()
    when = follow_up.scheduled_date
    if when is not None and when < today:
        return "OVERDUE"
    if when is not None and when == today:
        return "DUE"
    if rescheduled:
        return "RESCHEDULED"
    return "SCHEDULED"


def complete_follow_up(
    db: Session,
    follow_up: FollowUp,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> FollowUp:
    if (follow_up.status or "PENDING").upper() in ("COMPLETED", "CANCELLED"):
        raise TrackingError("Follow-up already finished.", 409)
    follow_up.status = "COMPLETED"
    follow_up.completed_date = date.today()
    follow_up.completed_at = datetime.now()
    if notes:
        follow_up.notes = (follow_up.notes or "") + f"\n{notes}".strip()
    record_application_event(
        db,
        follow_up.application_id,
        "FOLLOW_UP_COMPLETED",
        source=source,
        previous_status=None,
        new_status=None,
        notes=notes or "Follow-up completed.",
    )
    db.flush()
    return follow_up


def reschedule_follow_up(
    db: Session,
    follow_up: FollowUp,
    *,
    scheduled_date: date,
    notes: str | None = None,
    source: str = "USER",
) -> FollowUp:
    if (follow_up.status or "PENDING").upper() == "COMPLETED":
        raise TrackingError("Completed follow-ups cannot be rescheduled.", 409)
    if (follow_up.status or "PENDING").upper() == "CANCELLED":
        raise TrackingError("Cancelled follow-ups cannot be rescheduled.", 409)
    previous = follow_up.scheduled_date
    follow_up.scheduled_date = scheduled_date
    follow_up.reminder_date = scheduled_date
    if notes:
        follow_up.notes = (follow_up.notes or "") + f"\n{notes}".strip()
    record_application_event(
        db,
        follow_up.application_id,
        "FOLLOW_UP_RESCHEDULED",
        source=source,
        previous_status=None,
        new_status=None,
        notes=f"Rescheduled from {previous.isoformat()} to {scheduled_date.isoformat()}.",
    )
    db.flush()
    return follow_up


def cancel_follow_up(
    db: Session,
    follow_up: FollowUp,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> FollowUp:
    if (follow_up.status or "PENDING").upper() in ("COMPLETED", "CANCELLED"):
        raise TrackingError("Follow-up already finished.", 409)
    follow_up.status = "CANCELLED"
    if notes:
        follow_up.notes = (follow_up.notes or "") + f"\n{notes}".strip()
    record_application_event(
        db,
        follow_up.application_id,
        "FOLLOW_UP_CANCELLED",
        source=source,
        previous_status=None,
        new_status=None,
        notes=notes or "Follow-up cancelled.",
    )
    db.flush()
    return follow_up


def skip_follow_up(
    db: Session,
    follow_up: FollowUp,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> FollowUp:
    """Skip a follow-up without treating it as completed (e.g. no action
    needed). Distinct from cancellation: skipped is a deliberate "don't
    follow up on this trigger" decision with its own immutable event."""
    if (follow_up.status or "PENDING").upper() in (
        "COMPLETED",
        "CANCELLED",
        "SKIPPED",
    ):
        raise TrackingError("Follow-up already finished.", 409)
    follow_up.status = "SKIPPED"
    follow_up.skipped_at = datetime.now()
    if notes:
        follow_up.notes = (follow_up.notes or "") + f"\n{notes}".strip()
    record_application_event(
        db,
        follow_up.application_id,
        "FOLLOW_UP_SKIPPED",
        source=source,
        previous_status=None,
        new_status=None,
        notes=notes or "Follow-up skipped.",
    )
    db.flush()
    return follow_up


def restore_follow_up(
    db: Session,
    follow_up: FollowUp,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> FollowUp:
    """Reopen a cancelled/skipped follow-up (keeps the original scheduled date
    unless it already passed, in which case it moves to today). Any historical
    terminal events stay in the immutable timeline."""
    if (follow_up.status or "PENDING").upper() in ("PENDING",):
        raise TrackingError("Follow-up is already active.", 409)
    previous = (follow_up.status or "PENDING").upper()
    follow_up.status = "PENDING"
    today = date.today()
    if follow_up.scheduled_date is not None and follow_up.scheduled_date < today:
        follow_up.scheduled_date = today
        follow_up.reminder_date = today
    follow_up.skipped_at = None
    if notes:
        follow_up.notes = (follow_up.notes or "") + f"\n{notes}".strip()
    record_application_event(
        db,
        follow_up.application_id,
        "FOLLOW_UP_RESTORED",
        source=source,
        previous_status=None,
        new_status=None,
        notes=notes or f"Follow-up reopened (was {previous}).",
        metadata={"restored_from": previous},
    )
    db.flush()
    return follow_up


def package_for_application(
    db: Session, application: Application
) -> ApplicationPackage | None:
    return db.scalar(
        select(ApplicationPackage)
        .where(ApplicationPackage.job_id == application.job_id)
        .order_by(
            ApplicationPackage.version.desc(),
            ApplicationPackage.id.desc(),
        )
        .limit(1)
    )


def resume_snapshot_from_package(
    db: Session, application: Application
) -> None:
    """Snapshot resume name/version at tracking time so historical applications
    survive the resume row being deactivated/archived/deleted later."""
    if application.resume_name is not None and application.resume_id is not None:
        return
    package = package_for_application(db, application)
    if package is None or package.selected_resume_id is None:
        return
    resume = db.get(Resume, package.selected_resume_id)
    if resume is None:
        return
    application.resume_id = package.selected_resume_id
    application.resume_name = resume.name
    application.resume_version = resume.version


# Keep the controlled vocabularies importable from here for convenience.
__all__ = [
    "TRACKING_STATUSES",
    "FOLLOW_UP_STATUSES",
]
