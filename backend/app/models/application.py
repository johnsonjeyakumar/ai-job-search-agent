from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Application(Base):
    """Job application record and its lifecycle status."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), index=True
    )
    # Legacy short status: discovered | saved | preparing | applied | ...
    # Kept for backward compatibility with Phase 6/7 code paths.
    status: Mapped[str] = mapped_column(String(50), default="discovered")
    # Phase 8 controlled lifecycle (see app/models/application_tracking.py).
    # The single source of truth for the tracking funnel; `status` mirrors it.
    lifecycle_status: Mapped[str] = mapped_column(
        String(40), default="DISCOVERED", index=True
    )
    # Phase 9: where the application was actually submitted (e.g. linkedin,
    # indeed, company_career). Distinct from job.source (discovery source).
    # NULL until a real submission platform is known — never fabricated.
    application_source: Mapped[str | None] = mapped_column(
        String(100), index=True
    )
    # Historical resume snapshot: keeps the identity/version of the resume used
    # even if the resume row is later deactivated/archived/deleted.
    resume_name: Mapped[str | None] = mapped_column(String(255))
    resume_version: Mapped[str | None] = mapped_column(String(50))
    applied_date: Mapped[date | None] = mapped_column(Date, index=True)
    interview_date: Mapped[date | None] = mapped_column(Date)
    application_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RecruiterContact(Base):
    """Recruiter / hiring contact linked to a job or application."""

    __tablename__ = "recruiter_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FollowUp(Base):
    """Scheduled / completed follow-up on an application or contact."""

    __tablename__ = "follow_ups"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    recruiter_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("recruiter_contacts.id", ondelete="SET NULL"), index=True
    )
    action_type: Mapped[str] = mapped_column(String(100))
    # PENDING | COMPLETED | CANCELLED | SKIPPED (SCHEDULED/DUE/OVERDUE/
    # RESCHEDULED are derived at read time from the event history + dates).
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # Phase 9 follow-up engineering: deterministic priority / reason / trigger.
    # priority: HIGH | MEDIUM | LOW
    priority: Mapped[str | None] = mapped_column(String(10))
    # reason: SUBMISSION_FOLLOW_UP | INTERVIEW_THANK_YOU
    reason: Mapped[str | None] = mapped_column(String(50))
    # The lifecycle status that caused this follow-up to be scheduled.
    trigger_status: Mapped[str | None] = mapped_column(String(40))
    # Dedupe key, e.g. "app:12:SUBMISSION_FOLLOW_UP" or
    # "app:12:INTERVIEW_THANK_YOU:5". One follow-up per trigger, no matter how
    # often the trigger endpoint is hit.
    trigger_key: Mapped[str | None] = mapped_column(String(100), index=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    reminder_date: Mapped[date | None] = mapped_column(Date)
    completed_date: Mapped[date | None] = mapped_column(Date)
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
