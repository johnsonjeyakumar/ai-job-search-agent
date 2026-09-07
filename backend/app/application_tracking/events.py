"""Immutable application-history recording (Phase 8).

Every status/event change is appended to ``application_events``. Rows are
never updated or deleted by normal operations; manual corrections append a new
``STATUS_CORRECTED`` event.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application_tracking import (
    APPLICATION_EVENTS,
    ApplicationEvent,
)

ALLOWED_EVENT_TYPES = frozenset(APPLICATION_EVENTS)


class InvalidEventTypeError(Exception):
    pass


def record_application_event(
    db: Session,
    application_id: int,
    event_type: str,
    *,
    source: str = "USER",
    previous_status: str | None = None,
    new_status: str | None = None,
    notes: str | None = None,
    metadata: dict | None = None,
    event_timestamp: datetime | None = None,
) -> ApplicationEvent:
    """Append one immutable event to the application history.

    ``event_timestamp`` is normally server-defaulted to now; callers can pass a
    specific timestamp to backfill real events known to have happened (e.g. a
    submission that already occurred before this phase).
    """
    event_type = event_type.upper()
    if event_type not in ALLOWED_EVENT_TYPES:
        raise InvalidEventTypeError(f"Unknown application event type: {event_type!r}")

    event = ApplicationEvent(
        application_id=application_id,
        event_type=event_type,
        previous_status=previous_status,
        new_status=new_status,
        source=source,
        notes=notes,
        event_metadata=metadata or {},
    )
    if event_timestamp is not None:
        event.event_timestamp = event_timestamp
    db.add(event)
    return event


def timeline(db: Session, application_id: int) -> list[ApplicationEvent]:
    """Chronologically ordered, immutable timeline for one application."""
    return list(
        db.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(
                ApplicationEvent.event_timestamp.asc(),
                ApplicationEvent.id.asc(),
            )
        )
    )


def latest_event(db: Session, application_id: int) -> ApplicationEvent | None:
    row = db.scalar(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(
            ApplicationEvent.event_timestamp.desc(),
            ApplicationEvent.id.desc(),
        )
        .limit(1)
    )
    return row


def reached_milestone_at(
    db: Session,
    application_id: int,
    event_type: str,
) -> datetime | None:
    """Timestamp of the FIRST event that carried the application into a stage."""
    row = db.scalar(
        select(ApplicationEvent.event_timestamp)
        .where(ApplicationEvent.application_id == application_id)
        .where(ApplicationEvent.event_type == event_type)
        .order_by(
            ApplicationEvent.event_timestamp.asc(),
            ApplicationEvent.id.asc(),
        )
        .limit(1)
    )
    return row
