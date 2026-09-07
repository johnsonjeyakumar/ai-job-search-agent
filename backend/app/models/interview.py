"""Interview domain models (Phase 10).

Interview is the primary entity. InterviewRecord (Phase 8) is preserved for
backward compatibility — the new model adds richer fields (interviewer,
meeting_url, outcome, etc.) and supports multiple rounds via the ``round``
column. Application lifecycle_status remains authoritative; Interview status
is interview-specific only.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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
# Controlled vocabularies
# ---------------------------------------------------------------------------
INTERVIEW_STATUSES = (
    "SCHEDULED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
    "RESCHEDULED",
)

INTERVIEW_OUTCOMES = (
    "PENDING",
    "PASSED",
    "REJECTED",
    "NEXT_ROUND",
    "OFFER",
    "WITHDRAWN",
    "NO_DECISION",
)

INTERVIEW_TYPES = (
    "TELEPHONE",
    "VIDEO",
    "TECHNICAL",
    "BEHAVIORAL",
    "CODING",
    "HR",
    "PANEL",
    "FINAL",
    "OTHER",
)

QUESTION_CATEGORIES = (
    "TECHNICAL",
    "BEHAVIORAL",
    "HR",
    "PROJECT",
    "RESUME_BASED",
    "ROLE_SPECIFIC",
)

QUESTION_DIFFICULTIES = ("EASY", "MEDIUM", "HARD")

QUESTION_PRIORITIES = ("HIGH", "MEDIUM", "LOW")

QUESTION_SOURCES = (
    "JOB_REQUIREMENT",
    "RESUME_EVIDENCE",
    "ROLE_PATTERN",
    "GENERAL",
)

SESSION_CONFIG_MIX = ("TECHNICAL", "BEHAVIORAL", "PROJECT", "HR", "RESUME_BASED")

PREP_ITEM_STATUSES = ("TODO", "IN_PROGRESS", "COMPLETED")


class Interview(Base):
    """Comprehensive interview record (Phase 10)."""

    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_type: Mapped[str] = mapped_column(String(40), default="OTHER")
    round: Mapped[int] = mapped_column(Integer, default=1)
    interviewer_name: Mapped[str | None] = mapped_column(String(255))
    interviewer_role: Mapped[str | None] = mapped_column(String(255))
    meeting_url: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="SCHEDULED")
    outcome: Mapped[str] = mapped_column(String(30), default="PENDING")
    notes: Mapped[str | None] = mapped_column(Text)
    feedback_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InterviewQuestion(Base):
    """Generated or user-created interview question."""

    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int | None] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL"), index=True
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="TECHNICAL")
    difficulty: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    source: Mapped[str] = mapped_column(String(30), default="GENERAL")
    rationale: Mapped[str | None] = mapped_column(Text)
    source_context: Mapped[str | None] = mapped_column(Text)
    draft_answer: Mapped[str | None] = mapped_column(Text)
    answer_feedback: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InterviewSession(Base):
    """Mock interview session (Phase 10)."""

    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[int | None] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    questions: Mapped[list] = mapped_column(JSONB, default=list)
    answers: Mapped[list] = mapped_column(JSONB, default=list)
    feedback: Mapped[dict] = mapped_column(JSONB, default=dict)
    final_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InterviewPrepItem(Base):
    """Preparation plan item (Phase 10)."""

    __tablename__ = "interview_prep_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="TODO")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
