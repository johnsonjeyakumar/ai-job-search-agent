from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class OpportunityScore(Base):
    """Final opportunity decision for a job (Phase 5).

    Combines the personal match score with the Phase 4 job-quality signals
    into a single, transparent decision. The match/quality/freshness/company
    building blocks are stored separately so the composite is auditable.
    """

    __tablename__ = "opportunity_scores"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "profile_id",
            "opportunity_version",
            name="uq_opportunity_scores_job_profile_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    quality_score: Mapped[int | None] = mapped_column()
    freshness_score: Mapped[int | None] = mapped_column()
    company_score: Mapped[int | None] = mapped_column()
    opportunity_score: Mapped[float] = mapped_column(Numeric(5, 2), index=True)
    recommendation: Mapped[str] = mapped_column(
        String(20), index=True
    )  # APPLY_NOW | APPLY | REVIEW | LOW_PRIORITY | SKIP
    opportunity_version: Mapped[str] = mapped_column(String(20), default="v1")
    explanation: Mapped[list] = mapped_column(JSONB, default=list)
    blockers: Mapped[list] = mapped_column(JSONB, default=list)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
