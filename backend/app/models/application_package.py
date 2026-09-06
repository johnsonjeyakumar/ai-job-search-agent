"""Application preparation engine models (Phase 6).

An ``ApplicationPackage`` is a reviewable, job-specific application package
built for a selected real job. It never submits anything; it only prepares.
Statuses stop at ``APPROVED`` (approved for execution, not actually applied).
All child rows hang off the package so prior versions stay preserved.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

PACKAGE_STATUSES = (
    "DRAFT",
    "GENERATING",
    "NEEDS_REVIEW",
    "READY_FOR_REVIEW",
    "APPROVED",
    "ARCHIVED",
)

PACKAGE_READINESS = ("NOT_READY", "READY")

QUALITY_GATES = ("PASS", "NEEDS_REVIEW", "FAIL")


class ApplicationPackage(Base):
    """A versioned, reviewable application package for one real job."""

    __tablename__ = "application_packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    selected_resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    # DRAFT | GENERATING | NEEDS_REVIEW | READY_FOR_REVIEW | APPROVED | ARCHIVED
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    # READY | NOT_READY  (package completeness, NOT a hire probability)
    readiness: Mapped[str] = mapped_column(String(20), default="NOT_READY")
    readiness_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    # PASS | NEEDS_REVIEW | FAIL
    quality_gate: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")
    quality_gate_summary: Mapped[str | None] = mapped_column(Text)

    # Phase 5 signals captured at prepare time (read-only snapshot).
    match_score: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(20), default="REVIEW")

    # Deterministic selection result {selected_resume_id, score, explanation, evidence, candidates}
    resume_selection: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Aggregate gap analysis {term, category, status, evidence, source, confidence}
    gap_analysis: Mapped[list] = mapped_column(JSONB, default=list)

    cover_letter: Mapped[str | None] = mapped_column(Text)
    # skipped | generated | needs_review | error
    cover_letter_status: Mapped[str] = mapped_column(String(30), default="skipped")

    # Human-facing note when a prior package exists for the same job.
    duplicate_disclaimer: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationEvidence(Base):
    """Evidence-mapped requirement: real evidence vs a job requirement."""

    __tablename__ = "application_evidence_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("application_packages.id", ondelete="CASCADE"), index=True
    )
    requirement: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(50))
    # MATCHED | PARTIAL | MISSING_EVIDENCE | UNKNOWN
    status: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[str | None] = mapped_column(Text)
    # profile | resume | project | internship | education | certification | preferences | job
    source: Mapped[str] = mapped_column(String(50), default="job")
    # HIGH | MEDIUM | LOW
    confidence: Mapped[str] = mapped_column(String(10), default="LOW")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApplicationTailoringSuggestion(Base):
    """Suggested resume adjustment grounded in existing evidence.

    ``review_status`` distinguishes wording that merely re-frames existing
    evidence (``SAFE_TO_APPLY``) from wording that would assert something new
    (``NEEDS_USER_REVIEW``). The original resume is never modified here.
    """

    __tablename__ = "application_tailoring_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("application_packages.id", ondelete="CASCADE"), index=True
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), index=True
    )
    requirement: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(50))
    existing_evidence: Mapped[str | None] = mapped_column(Text)
    suggested_wording: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    # HIGH | MEDIUM | LOW
    confidence: Mapped[str] = mapped_column(String(10), default="LOW")
    # SAFE_TO_APPLY | NEEDS_USER_REVIEW
    review_status: Mapped[str] = mapped_column(String(30), default="NEEDS_USER_REVIEW")
    applied: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApplicationAnswer(Base):
    """One application question answered from real profile evidence only."""

    __tablename__ = "application_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("application_packages.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(50))
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str | None] = mapped_column(Text)
    source_evidence: Mapped[list] = mapped_column(JSONB, default=list)
    # HIGH | MEDIUM | LOW
    confidence: Mapped[str] = mapped_column(String(10), default="LOW")
    # VALID | NEEDS_REVIEW | INVALID
    validation_status: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")
    feedback: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationValidationFinding(Base):
    """A single truth/consistency check result for a package."""

    __tablename__ = "application_validation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(
        ForeignKey("application_packages.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(50))
    check: Mapped[str] = mapped_column(String(255))
    # PASS | WARN | NEEDS_REVIEW | INVALID | FAIL
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
