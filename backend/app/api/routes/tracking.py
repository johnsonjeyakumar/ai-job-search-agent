"""Application tracking API (Phase 8): status, timeline, notes, follow-ups."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.application_tracking.events import timeline
from app.application_tracking.status import InvalidStatusError
from app.database.session import get_db
from app.models.application_tracking import (
    APPLICATION_EVENTS,
    TRACKING_STATUSES,
)
from app.schemas.application_tracking import (
    FollowUpCompleteRequest,
    FollowUpRescheduleRequest,
    FollowUpRestoreRequest,
    FollowUpScheduleRequest,
    FollowUpSkipRequest,
    InterviewCreateRequest,
    NoteAddRequest,
    OfferCreateRequest,
    ResponseCreateRequest,
    StatusUpdateRequest,
)
from app.services import application_analytics_service as analytics
from app.services import application_lifecycle_service as lifecycle

router = APIRouter(prefix="/tracking", tags=["tracking"])

_ALLOWED_SORTS = ("newest", "oldest", "waiting", "follow_up_due", "company", "role")


def _handle(e: Exception) -> HTTPException:
    if isinstance(e, lifecycle.TrackingError):
        return HTTPException(status_code=e.status_code, detail=e.message)
    if isinstance(e, ValueError):
        return HTTPException(status_code=422, detail=str(e))
    if isinstance(e, InvalidStatusError):
        return HTTPException(status_code=422, detail=f"Invalid application status: {e.value!r}")
    return HTTPException(status_code=500, detail="Internal server error.")


def _application_or_404(db: Session, application_id: int):
    application = db.get(lifecycle.Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
    return application


@router.get("/applications")
def list_applications(
    status: str | None = Query(default=None),
    company: str | None = Query(default=None),
    role: str | None = Query(default=None),
    location: str | None = Query(default=None),
    source: str | None = Query(default=None),
    resume: str | None = Query(default=None),
    follow_up: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    sort: str = Query(default="newest"),
    db: Session = Depends(get_db),
) -> dict:
    if sort not in _ALLOWED_SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {_ALLOWED_SORTS}")
    if status and status not in TRACKING_STATUSES:
        raise _handle(InvalidStatusError(status))
    try:
        rows = analytics.tracking_rows(
            db,
            status=status,
            company=company,
            role=role,
            location=location,
            source=source,
            resume=resume,
            follow_up=follow_up,
            from_date=from_date,
            to_date=to_date,
            sort=sort,
        )
    except ValueError as exc:
        raise _handle(exc) from exc
    counts = {
        label: sum(1 for r in rows if r["status"] == label)
        for label in TRACKING_STATUSES
    }
    return {
        "total": len(rows),
        "status_counts": counts,
        "items": rows,
        "filters": {
            "status": status, "company": company, "role": role,
            "location": location, "source": source, "resume": resume,
            "follow_up": follow_up, "from_date": from_date, "to_date": to_date,
            "sort": sort,
        },
    }


@router.get("/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db)) -> dict:
    _application_or_404(db, application_id)
    rows = analytics.tracking_rows(db, sort="newest")
    row = next((r for r in rows if r["id"] == application_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
    event_rows = timeline(db, application_id)
    timeline_items = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "previous_status": e.previous_status,
            "new_status": e.new_status,
            "source": e.source,
            "notes": e.notes,
            "metadata": e.event_metadata,
            "event_timestamp": e.event_timestamp.isoformat() if e.event_timestamp else None,
        }
        for e in event_rows
    ]
    responses = [
        {
            "id": r.id,
            "category": r.category,
            "received_at": r.received_at.isoformat() if r.received_at else None,
            "notes": r.notes,
        }
        for r in db.query(lifecycle.ApplicationResponse)
        .filter_by(application_id=application_id)
        .order_by(lifecycle.ApplicationResponse.received_at.desc())
    ]
    interviews = [
        {
            "id": r.id,
            "interview_date": r.interview_date.isoformat() if r.interview_date else None,
            "interview_type": r.interview_type,
            "round": getattr(r, "round", None),
            "status": r.status,
            "notes": r.notes,
        }
        for r in db.query(lifecycle.InterviewRecord)
        .filter_by(application_id=application_id)
        .order_by(lifecycle.InterviewRecord.interview_date.desc())
    ]
    offers = [
        {
            "id": r.id,
            "offer_date": r.offer_date.isoformat() if r.offer_date else None,
            "status": r.status,
            "notes": r.notes,
        }
        for r in db.query(lifecycle.OfferRecord)
        .filter_by(application_id=application_id)
        .order_by(lifecycle.OfferRecord.offer_date.desc())
    ]
    follow_ups = analytics.follow_up_summary(db)["items"]
    follow_ups = [f for f in follow_ups if f["application_id"] == application_id]
    return {**row, "timeline": timeline_items, "responses": responses,
            "interviews": interviews, "offers": offers, "follow_ups": follow_ups}


@router.patch("/applications/{application_id}/status")
def update_status(
    application_id: int,
    payload: StatusUpdateRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        application = lifecycle.set_status_manual(
            db,
            application_id,
            payload.target_status,
            override=payload.override,
            notes=payload.notes,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    rows = analytics.tracking_rows(db, sort="newest")
    row = next((r for r in rows if r["id"] == application_id), None)
    return {
        "application": row,
        "message": (
            f"Status corrected to {application.lifecycle_status} "
            "(recorded as STATUS_CORRECTED)."
            if payload.override
            else f"Status updated to {application.lifecycle_status}."
        ),
    }


@router.post("/applications/{application_id}/notes")
def add_note(
    application_id: int,
    payload: NoteAddRequest,
    db: Session = Depends(get_db),
) -> dict:
    application = _application_or_404(db, application_id)
    lifecycle.add_note(db, application, payload.notes)
    db.commit()
    return {"message": "Note added.", "notes": application.notes}


@router.post("/applications/{application_id}/responses")
def add_response(
    application_id: int,
    payload: ResponseCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    application = _application_or_404(db, application_id)
    try:
        row = lifecycle.record_response(
            db, application,
            category=payload.category,
            received_at=payload.received_at,
            notes=payload.notes,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Response recorded.", "response_id": row.id,
            "status": application.lifecycle_status}


@router.post("/applications/{application_id}/interviews")
def add_interview(
    application_id: int,
    payload: InterviewCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    application = _application_or_404(db, application_id)
    try:
        row = lifecycle.record_interview(
            db, application,
            interview_date=payload.interview_date,
            interview_type=payload.interview_type,
            round_number=payload.round_number,
            status=payload.status,
            notes=payload.notes,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Interview recorded.", "interview_id": row.id,
            "status": application.lifecycle_status}


@router.post("/applications/{application_id}/offers")
def add_offer(
    application_id: int,
    payload: OfferCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    application = _application_or_404(db, application_id)
    try:
        row = lifecycle.record_offer(
            db, application,
            offer_date=payload.offer_date,
            status=payload.status,
            notes=payload.notes,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Offer recorded.", "offer_id": row.id,
            "status": application.lifecycle_status}


@router.get("/applications/{application_id}/follow-ups")
def list_application_follow_ups(
    application_id: int, db: Session = Depends(get_db)
) -> dict:
    _application_or_404(db, application_id)
    items = analytics.follow_up_summary(db)["items"]
    items = [f for f in items if f["application_id"] == application_id]
    return {"items": items}


@router.post("/applications/{application_id}/follow-ups")
def schedule_follow_up(
    application_id: int,
    payload: FollowUpScheduleRequest,
    db: Session = Depends(get_db),
) -> dict:
    application = _application_or_404(db, application_id)
    try:
        row = lifecycle.create_follow_up(
            db, application, source="USER", scheduled_date=payload.scheduled_date
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    if row is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Follow-up already exists, or the application is "
                "rejected/withdrawn/has a response."
            ),
        )
    return {"message": "Follow-up scheduled.", "follow_up_id": row.id}


@router.get("/follow-ups")
def list_follow_ups(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    due: bool = Query(default=False),
    overdue: bool = Query(default=False),
    application_id: int | None = Query(default=None),
    company: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return analytics.follow_ups_list(
            db,
            status=status,
            priority=priority,
            due=due,
            overdue=overdue,
            application_id=application_id,
            company=company,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise _handle(exc) from exc


@router.get("/follow-ups/summary")
def follow_ups_summary(db: Session = Depends(get_db)) -> dict:
    return analytics.follow_up_summary(db)


@router.get("/follow-ups/{follow_up_id}")
def get_follow_up(follow_up_id: int, db: Session = Depends(get_db)) -> dict:
    _follow_up_or_404(db, follow_up_id)
    items = analytics.follow_up_summary(db)["items"]
    row = next((f for f in items if f["id"] == follow_up_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Follow-up {follow_up_id} not found")
    return row


@router.post("/follow-ups/{follow_up_id}/skip")
def skip_follow_up(
    follow_up_id: int,
    payload: FollowUpSkipRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    follow_up = _follow_up_or_404(db, follow_up_id)
    try:
        lifecycle.skip_follow_up(
            db, follow_up, notes=payload.notes if payload else None
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Follow-up skipped.", "follow_up_id": follow_up.id}


@router.post("/follow-ups/{follow_up_id}/restore")
def restore_follow_up(
    follow_up_id: int,
    payload: FollowUpRestoreRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    follow_up = _follow_up_or_404(db, follow_up_id)
    try:
        lifecycle.restore_follow_up(
            db, follow_up, notes=payload.notes if payload else None
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Follow-up restored.", "follow_up_id": follow_up.id}


def _follow_up_or_404(db: Session, follow_up_id: int):
    follow_up = db.get(lifecycle.FollowUp, follow_up_id)
    if follow_up is None:
        raise HTTPException(status_code=404, detail=f"Follow-up {follow_up_id} not found")
    return follow_up


@router.post("/follow-ups/{follow_up_id}/complete")
def complete_follow_up(
    follow_up_id: int,
    payload: FollowUpCompleteRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    follow_up = _follow_up_or_404(db, follow_up_id)
    try:
        lifecycle.complete_follow_up(
            db, follow_up, notes=payload.notes if payload else None
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Follow-up completed.", "follow_up_id": follow_up.id}


@router.post("/follow-ups/{follow_up_id}/reschedule")
def reschedule_follow_up(
    follow_up_id: int,
    payload: FollowUpRescheduleRequest,
    db: Session = Depends(get_db),
) -> dict:
    follow_up = _follow_up_or_404(db, follow_up_id)
    try:
        lifecycle.reschedule_follow_up(
            db, follow_up, scheduled_date=payload.scheduled_date, notes=payload.notes
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Follow-up rescheduled.", "follow_up_id": follow_up.id}


@router.post("/follow-ups/{follow_up_id}/cancel")
def cancel_follow_up(
    follow_up_id: int,
    payload: FollowUpCompleteRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    follow_up = _follow_up_or_404(db, follow_up_id)
    try:
        lifecycle.cancel_follow_up(
            db, follow_up, notes=payload.notes if payload else None
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Follow-up cancelled.", "follow_up_id": follow_up.id}


@router.get("/statuses")
def statuses() -> dict:
    return {
        "statuses": list(TRACKING_STATUSES),
        "transitions": {
            k: sorted(v) for k, v in lifecycle.app_status.TRANSITIONS.items()
        },
        "event_types": list(APPLICATION_EVENTS),
    }


__all__ = ["router"]
