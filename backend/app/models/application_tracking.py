"""Application tracking models and controlled vocabulary (Phase 8).

The application lifecycle is a controlled state machine: statuses are the
strings in ``TRACKING_STATUSES`` and transitions are only legal per
``TRANSITIONS`` (see ``app/application_tracking/status.py``). Nothing here
stores credentials or secrets. All tracking history is written to
:class:`ApplicationEvent` rows, which are immutable history records.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# ---------------------------------------------------------------------------
# Application lifecycle (tracking) statuses — controlled vocabulary.
# These live on ``applications.lifecycle_status`` and in application events.
# ---------------------------------------------------------------------------
TRACKING_STATUSES = (
    "DISCOVERED",
    "SHORTLISTED",
    "PREPARING",
    "READY_FOR_REVIEW",
    "APPROVED",
    "EXECUTION_READY",
    "EXECUTING",
    "SUBMITTED",
    "SUBMISSION_CONFIRMED",
    "RESPONSE_RECEIVED",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
    "EXPIRED",
    "CANCELLED",
)

# Legacy `applications.status` short forms kept in sync for backward
# compatibility with Phase 6/7 code (dup-check, package disclaimers).
LEGACY_STATUS_MAP = {
    "DISCOVERED": "saved",
    "SHORTLISTED": "saved",
    "PREPARING": "preparing",
    "READY_FOR_REVIEW": "preparing",
    "APPROVED": "approved",
    "EXECUTION_READY": "approved",
    "EXECUTING": "applying",
    "SUBMITTED": "applied",
    "SUBMISSION_CONFIRMED": "submitted",
    "RESPONSE_RECEIVED": "responded",
    "INTERVIEW": "interviewing",
    "OFFER": "offered",
    "REJECTED": "rejected",
    "WITHDRAWN": "withdrawn",
    "EXPIRED": "expired",
    "CANCELLED": "cancelled",
}

# Where a status/event change came from. Never claim the system detected a
# response automatically when the user entered it manually.
EVENT_SOURCES = ("USER", "SYSTEM", "BROWSER", "EXECUTION", "IMPORT", "API")

# Possible application-event types (immutable history markers).
APPLICATION_EVENTS = (
    "APPLICATION_CREATED",
    "SHORTLISTED",
    "PACKAGE_PREPARED",
    "PACKAGE_READY_FOR_REVIEW",
    "APPROVED",
    "EXECUTION_READY",
    "EXECUTION_STARTED",
    "SUBMITTED",
    "SUBMISSION_CONFIRMED",
    "RESPONSE_RECEIVED",
    "INTERVIEW_SCHEDULED",
    "INTERVIEW_COMPLETED",
    "OFFER_RECEIVED",
    "REJECTED",
    "WITHDRAWN",
    "EXPIRED",
    "CANCELLED",
    "FOLLOW_UP_SCHEDULED",
    "FOLLOW_UP_DUE",
    "FOLLOW_UP_COMPLETED",
    "FOLLOW_UP_RESCHEDULED",
    "FOLLOW_UP_CANCELLED",
    "STATUS_CORRECTED",
    "NOTE_ADDED",
)

# Structured application-response categories (Phase 8, item 20).
RESPONSE_CATEGORIES = (
    "NO_RESPONSE",
    "RECRUITER_CONTACT",
    "ASSESSMENT",
    "INTERVIEW",
    "REJECTED",
    "OFFER",
    "OTHER",
)

INTERVIEW_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW", "OTHER")
INTERVIEW_TYPES = (
    "TELEPHONE",
    "VIDEO",
    "TECHNICAL",
    "BEHAVIORAL",
    "CODING",
    "HR",
    "PANEL",
    "OTHER",
)

OFFER_STATUSES = ("RECEIVED", "ACCEPTED", "DECLINED", "EXPIRED")

FOLLOW_UP_STATUSES = ("PENDING", "COMPLETED", "CANCELLED")
# ``DUE`` is derived at read time from scheduled_date vs today when the
# follow-up is neither COMPLETED nor CANCELLED.

SMALL_SAMPLE_THRESHOLD = 5


class ApplicationEvent(Base):
    """Immutable, ordered application-history record.

    Events are append-only: normal UI operations never modify or delete old
    rows. Manual corrections create a new ``STATUS_CORRECTED`` event instead
    of silently rewriting state.
    """

    __tablename__ = "application_events"
    __table_args__ = (
        # order rows deterministically within one application
        None,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # USER | SYSTEM | BROWSER | EXECUTION | IMPORT | API
    source: Mapped[str] = mapped_column(String(20), default="USER")
    notes: Mapped[str | None] = mapped_column(Text)
    # Column is named "metadata" in the DB; the ORM attribute avoids the
    # reserved class attribute name.
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApplicationResponse(Base):
    """A structured response received for an application."""

    __tablename__ = "application_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    # NO_RESPONSE | RECRUITER_CONTACT | ASSESSMENT | INTERVIEW | REJECTED |
    # OFFER | OTHER
    category: Mapped[str] = mapped_column(String(40))
    received_at: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InterviewRecord(Base):
    """Basic interview tracking (Phase 8 item 21). No prep content."""

    __tablename__ = "interview_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    interview_date: Mapped[date] = mapped_column(Date, index=True)
    # TELEPHONE | VIDEO | TECHNICAL | BEHAVIORAL | CODING | HR | PANEL | OTHER
    interview_type: Mapped[str] = mapped_column(String(40), default="OTHER")
    round: Mapped[int] = mapped_column(Integer, default=1)
    # SCHEDULED | COMPLETED | CANCELLED | NO_SHOW | OTHER
    status: Mapped[str] = mapped_column(String(30), default="SCHEDULED")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OfferRecord(Base):
    """Offer tracking (Phase 8 item 22). Minimal, non-sensitive fields."""

    __tablename__ = "offer_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    offer_date: Mapped[date] = mapped_column(Date, index=True)
    # RECEIVED | ACCEPTED | DECLINED | EXPIRED
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
