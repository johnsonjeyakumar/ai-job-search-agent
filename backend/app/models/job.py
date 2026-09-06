from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Job(Base):
    """Normalized job posting. Shared by all discovery sources."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_job_id", name="uq_jobs_source_source_job_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    company: Mapped[str] = mapped_column(String(255), index=True)
    location: Mapped[str | None] = mapped_column(String(255), index=True)
    remote_type: Mapped[str | None] = mapped_column(String(50))
    employment_type: Mapped[str | None] = mapped_column(String(50))
    experience_required: Mapped[str | None] = mapped_column(String(100))
    salary: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[list] = mapped_column(JSONB, default=list)
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), index=True, default="unknown")
    source_job_id: Mapped[str | None] = mapped_column(String(255))
    posted_date: Mapped[date | None] = mapped_column(Date, index=True)
    discovered_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # System lifecycle timestamps (distinct from posted_date which is the
    # employer's posting date).
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    application_url: Mapped[str | None] = mapped_column(Text)
    company_url: Mapped[str | None] = mapped_column(Text)


class JobMatch(Base):
    """Transparent match result between a job and a profile (Phase 5).

    ``match_score`` is the personal match (profile fit). The match-tier
    ``recommendation`` here is the derived band label for the match score
    alone; the final decision (combining job quality) lives in
    :class:`app.models.opportunity.OpportunityScore`.
    """

    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("job_id", "profile_id", name="uq_job_matches_job_profile"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    recommendation: Mapped[str] = mapped_column(
        String(20), default="review"
    )  # match-tier band: APPLY_NOW | APPLY | REVIEW | LOW_PRIORITY | SKIP
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    matching_version: Mapped[str] = mapped_column(
        String(20), default="v1", index=True
    )
    context_key: Mapped[str | None] = mapped_column(String(64), index=True)
    criteria_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
    matched_skills: Mapped[list] = mapped_column(JSONB, default=list)
    missing_skills: Mapped[list] = mapped_column(JSONB, default=list)
    matched_requirements: Mapped[list] = mapped_column(JSONB, default=list)
    partial_requirements: Mapped[list] = mapped_column(JSONB, default=list)
    missing_requirements: Mapped[list] = mapped_column(JSONB, default=list)
    unknown_requirements: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    explanation: Mapped[list] = mapped_column(JSONB, default=list)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
