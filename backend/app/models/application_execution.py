"""Application execution engine models (Phase 7).

An execution attaches to one approved application package and records, step by
step, how the apply workflow ran: which role/mode the policy selected, which
form fields were found and filled, whether the user approved submission, and
what verification evidence was captured afterwards. Nothing here stores
credentials. ``SUBMITTED`` is only written when a submission actually happened
and ``SUBMISSION_CONFIRMED`` only when explicit confirmation evidence exists.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

EXECUTION_STATUSES = (
    "EXECUTION_READY",
    "EXECUTING",
    "AWAITING_APPROVAL",
    "AWAITING_USER",
    "SUBMITTED",
    "SUBMISSION_CONFIRMED",
    "SUBMISSION_UNKNOWN",
    "EXECUTION_FAILED",
    "BLOCKED",
    "CANCELLED",
)

EXECUTION_MODES = (
    "AUTHORIZED_AUTOMATION",
    "PERMITTED_BROWSER",
    "HUMAN_ASSISTED",
    "UNSUPPORTED",
)

VERIFICATION_RESULTS = ("CONFIRMED", "LIKELY", "UNKNOWN", "FAILED")

STEP_STATUSES = ("pending", "running", "completed", "warning", "blocked", "error")


class ApplicationExecution(Base):
    """One application-execution attempt against one approved package."""

    __tablename__ = "application_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("application_packages.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(50))
    # AUTHORIZED_AUTOMATION | PERMITTED_BROWSER | HUMAN_ASSISTED | UNSUPPORTED
    execution_mode: Mapped[str] = mapped_column(String(30), default="HUMAN_ASSISTED")
    # EXECUTION_READY | EXECUTING | AWAITING_APPROVAL | AWAITING_USER |
    # SUBMITTED | SUBMISSION_CONFIRMED | SUBMISSION_UNKNOWN | EXECUTION_FAILED |
    # BLOCKED | CANCELLED
    status: Mapped[str] = mapped_column(String(30), default="EXECUTION_READY", index=True)
    current_step: Mapped[str | None] = mapped_column(String(60))
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # CONFIRMED | LIKELY | UNKNOWN | FAILED  (only meaningful after a submit)
    submission_status: Mapped[str | None] = mapped_column(String(30))
    confirmation_url: Mapped[str | None] = mapped_column(Text)
    confirmation_reference: Mapped[str | None] = mapped_column(String(255))
    # The "APPLICATION READY FOR SUBMISSION" payload shown before submission.
    approval_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # [{step, message}] accumulated while running.
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    # {fields_detected, fields_filled, fields_needing_review, answered_questions}
    execution_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Snapshot of the daily budget when this run started.
    daily_budget: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Phase 24: Idempotency and submission boundary
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    submission_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationExecutionStep(Base):
    """A named, ordered stage of an execution run."""

    __tablename__ = "application_execution_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("application_executions.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[str] = mapped_column(String(60))
    order: Mapped[int] = mapped_column(Integer, default=0)
    # pending | running | completed | warning | blocked | error
    status: Mapped[str] = mapped_column(String(30), default="running")
    message: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationExecutionEvidence(Base):
    """Verification evidence captured for an execution (no credentials)."""

    __tablename__ = "application_execution_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("application_executions.id", ondelete="CASCADE"), index=True
    )
    # screenshot_before | screenshot_after | confirmation_text |
    # confirmation_url | execution_step | user_note | reference
    kind: Mapped[str] = mapped_column(String(40))
    value: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExecutionLock(Base):
    """Execution lock row for cross-process coordination (Phase 24).

    One lock per package_id — only one worker may execute at a time.
    Advisory locks handle the actual concurrency; this table tracks ownership
    and heartbeat so stale locks can be detected and recovered.

    Note: package_id does NOT use a FK constraint. This is a coordination
    table, not a data relationship. The lock manager uses raw SQL anyway,
    and FKs would force tests to create entire parent chains unnecessarily.
    """

    __tablename__ = "execution_locks"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(
        Integer,
        index=True,
        unique=True,
    )
    execution_id: Mapped[int | None] = mapped_column(
        Integer,
    )
    owner_id: Mapped[str] = mapped_column(String(128))
    lock_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
