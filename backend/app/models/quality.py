"""Cached, versioned Job Quality Scores.

One row per (job, scoring_version): v1 is the current methodology and v2+ can
coexist later without destructive overwrites.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class JobQualityScore(Base):
    __tablename__ = "job_quality_scores"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "scoring_version",
            name="uq_job_quality_scores_job_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    # Member score 0-100; NULL when a signal is genuinely unavailable.
    freshness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requirements_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int] = mapped_column(Integer, index=True)
    scoring_version: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[list] = mapped_column(JSONB, default=list)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
