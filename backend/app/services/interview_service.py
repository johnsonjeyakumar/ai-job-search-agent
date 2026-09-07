"""Interview CRUD and lifecycle service (Phase 10).

Handles creation, update, completion, cancellation, rescheduling of
interviews. Does NOT create a competing application state machine — the
application lifecycle_status remains authoritative. Interview-specific
status lives on the Interview model only.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.interview import (
    INTERVIEW_OUTCOMES,
    INTERVIEW_STATUSES,
    INTERVIEW_TYPES,
    Interview,
    InterviewPrepItem,
)
from app.services import application_lifecycle_service as lifecycle

# Legal Interview.status transitions (interview-specific, not application-level).
_INTERVIEW_TRANSITIONS: dict[str, frozenset[str]] = {
    "SCHEDULED": frozenset({"IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW", "RESCHEDULED"}),
    "IN_PROGRESS": frozenset({"COMPLETED", "CANCELLED"}),
    "RESCHEDULED": frozenset({"IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW"}),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
    "NO_SHOW": frozenset(),
}

# Valid outcome transitions.
_OUTCOME_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset(
        {"PASSED", "REJECTED", "NEXT_ROUND", "OFFER", "WITHDRAWN", "NO_DECISION"}
    ),
    "NEXT_ROUND": frozenset(
        {"PASSED", "REJECTED", "NEXT_ROUND", "OFFER", "WITHDRAWN", "NO_DECISION"}
    ),
    "PASSED": frozenset({"NEXT_ROUND", "OFFER"}),
    "REJECTED": frozenset(),
    "OFFER": frozenset(),
    "WITHDRAWN": frozenset(),
    "NO_DECISION": frozenset(),
}


class InterviewError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _validate_interview_status(status: str) -> None:
    if status not in INTERVIEW_STATUSES:
        raise InterviewError(f"Invalid interview status: {status!r}", 409)


def _validate_interview_type(interview_type: str) -> None:
    if interview_type.upper() not in INTERVIEW_TYPES:
        raise InterviewError(f"Invalid interview type: {interview_type!r}", 409)


def _validate_outcome(outcome: str) -> None:
    if outcome not in INTERVIEW_OUTCOMES:
        raise InterviewError(f"Invalid interview outcome: {outcome!r}", 409)


_TERMINAL_INTERVIEW_STATUSES = frozenset({"COMPLETED", "CANCELLED", "NO_SHOW"})


def _can_transition(current: str, target: str) -> bool:
    if current in _TERMINAL_INTERVIEW_STATUSES:
        return False
    if current == target:
        return True
    allowed = _INTERVIEW_TRANSITIONS.get(current, frozenset())
    return target in allowed


def _can_transition_outcome(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in _OUTCOME_TRANSITIONS.get(current, frozenset())


def _application_or_raise(db: Session, application_id: int) -> Application:
    app = db.get(Application, application_id)
    if app is None:
        raise InterviewError(f"Application {application_id} not found.", 404)
    return app


def create_interview(
    db: Session,
    application_id: int,
    *,
    scheduled_at: datetime | None = None,
    interview_type: str = "OTHER",
    round_number: int = 1,
    interviewer_name: str | None = None,
    interviewer_role: str | None = None,
    meeting_url: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    source: str = "USER",
) -> Interview:
    """Create an interview record. Moves application to INTERVIEW if eligible."""
    app = _application_or_raise(db, application_id)
    _validate_interview_type(interview_type)

    row = Interview(
        application_id=application_id,
        scheduled_at=scheduled_at,
        interview_type=interview_type.upper(),
        round=round_number,
        interviewer_name=interviewer_name,
        interviewer_role=interviewer_role,
        meeting_url=meeting_url,
        location=location,
        status="SCHEDULED",
        outcome="PENDING",
        notes=notes,
    )
    db.add(row)
    db.flush()

    # Move application toward INTERVIEW lifecycle if possible.
    lifecycle._move_toward_target(
        db,
        app,
        target="INTERVIEW",
        source=source,
        notes=notes,
        event_type="INTERVIEW_SCHEDULED",
        metadata={"interview_type": interview_type, "round": round_number, "interview_id": row.id},
    )
    db.flush()

    # Create deterministic prep plan items.
    _create_default_prep_items(db, row, application_id)
    db.flush()

    # Schedule thank-you follow-up.
    if scheduled_at is not None:
        scheduled_at.date()
    lifecycle.schedule_interview_follow_up(
        db,
        app,
        _fake_interview_record(row),
        source=source if source in ("SYSTEM", "EXECUTION") else "USER",
    )
    db.flush()
    return row


def _fake_interview_record(row: Interview):
    """Create a lightweight object matching the interface schedule_interview_follow_up expects."""
    from app.models.application_tracking import InterviewRecord

    return InterviewRecord(
        application_id=row.application_id,
        interview_date=row.scheduled_at.date() if row.scheduled_at else date.today(),
        interview_type=row.interview_type,
        round=row.round,
        status=row.status,
    )


def update_interview(
    db: Session,
    interview_id: int,
    *,
    scheduled_at: datetime | None = None,
    interview_type: str | None = None,
    interviewer_name: str | None = None,
    interviewer_role: str | None = None,
    meeting_url: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> Interview:
    row = db.get(Interview, interview_id)
    if row is None:
        raise InterviewError(f"Interview {interview_id} not found.", 404)
    if scheduled_at is not None:
        row.scheduled_at = scheduled_at
    if interview_type is not None:
        _validate_interview_type(interview_type)
        row.interview_type = interview_type.upper()
    if interviewer_name is not None:
        row.interviewer_name = interviewer_name
    if interviewer_role is not None:
        row.interviewer_role = interviewer_role
    if meeting_url is not None:
        row.meeting_url = meeting_url
    if location is not None:
        row.location = location
    if notes is not None:
        row.notes = notes
    db.flush()
    return row


def get_interview(db: Session, interview_id: int) -> Interview:
    row = db.get(Interview, interview_id)
    if row is None:
        raise InterviewError(f"Interview {interview_id} not found.", 404)
    return row


def list_interviews_for_application(db: Session, application_id: int) -> list[Interview]:
    return list(
        db.scalars(
            select(Interview)
            .where(Interview.application_id == application_id)
            .order_by(Interview.round, Interview.created_at)
        ).all()
    )


def change_interview_status(
    db: Session,
    interview_id: int,
    target_status: str,
    *,
    source: str = "USER",
    notes: str | None = None,
) -> Interview:
    _validate_interview_status(target_status)
    row = get_interview(db, interview_id)
    if not _can_transition(row.status, target_status):
        raise InterviewError(
            f"Interview cannot move from {row.status} to {target_status}.", 409
        )
    row.status = target_status
    if target_status == "COMPLETED":
        row.completed_at = datetime.now()
    if notes:
        row.notes = (row.notes or "") + f"\n{notes}".strip()
    db.flush()
    return row


def complete_interview(
    db: Session,
    interview_id: int,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> Interview:
    return change_interview_status(
        db, interview_id, "COMPLETED", source=source, notes=notes
    )


def cancel_interview(
    db: Session,
    interview_id: int,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> Interview:
    return change_interview_status(
        db, interview_id, "CANCELLED", source=source, notes=notes
    )


def reschedule_interview(
    db: Session,
    interview_id: int,
    new_scheduled_at: datetime,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> Interview:
    row = get_interview(db, interview_id)
    if not _can_transition(row.status, "RESCHEDULED"):
        raise InterviewError(
            f"Interview in status {row.status!r} cannot be rescheduled.", 409
        )
    row.status = "RESCHEDULED"
    row.scheduled_at = new_scheduled_at
    if notes:
        row.notes = (row.notes or "") + f"\n{notes}".strip()
    db.flush()
    return row


def set_interview_outcome(
    db: Session,
    interview_id: int,
    outcome: str,
    *,
    notes: str | None = None,
    source: str = "USER",
) -> Interview:
    _validate_outcome(outcome)
    row = get_interview(db, interview_id)
    if not _can_transition_outcome(row.outcome, outcome):
        raise InterviewError(
            f"Interview outcome cannot move from {row.outcome} to {outcome}.", 409
        )
    row.outcome = outcome
    if notes:
        row.notes = (row.notes or "") + f"\n{notes}".strip()
    db.flush()
    return row


def set_interview_feedback(
    db: Session,
    interview_id: int,
    feedback: dict,
    *,
    source: str = "USER",
) -> Interview:
    row = get_interview(db, interview_id)
    row.feedback_json = feedback
    db.flush()
    return row


def interview_summary(db: Session, application_id: int) -> dict:
    """Return a summary of interviews for an application."""
    interviews = list_interviews_for_application(db, application_id)
    return {
        "total": len(interviews),
        "scheduled": sum(1 for i in interviews if i.status == "SCHEDULED"),
        "completed": sum(1 for i in interviews if i.status == "COMPLETED"),
        "cancelled": sum(1 for i in interviews if i.status == "CANCELLED"),
        "outcomes": {
            o: sum(1 for i in interviews if i.outcome == o)
            for o in INTERVIEW_OUTCOMES
        },
        "items": [
            {
                "id": i.id,
                "round": i.round,
                "interview_type": i.interview_type,
                "status": i.status,
                "outcome": i.outcome,
                "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
                "interviewer_name": i.interviewer_name,
                "location": i.location,
            }
            for i in interviews
        ],
    }


def _create_default_prep_items(
    db: Session, interview: Interview, application_id: int
) -> None:
    """Create default preparation plan items for a new interview."""
    items = [
        ("Resume questions", "RESUME_BASED"),
        ("Technical fundamentals", "TECHNICAL"),
        ("Job-specific technical", "TECHNICAL"),
        ("Project discussion", "PROJECT"),
        ("Behavioral", "BEHAVIORAL"),
        ("HR", "HR"),
        ("Mock interview", "MOCK"),
    ]
    for idx, (label, category) in enumerate(items):
        item = InterviewPrepItem(
            interview_id=interview.id,
            application_id=application_id,
            label=label,
            category=category,
            status="TODO",
            sort_order=idx,
        )
        db.add(item)
