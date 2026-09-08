from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Preferences(Base):
    """Editable job-search preferences used to filter and score jobs."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )

    preferred_locations: Mapped[list] = mapped_column(JSONB, default=list)
    experience_levels: Mapped[list] = mapped_column(JSONB, default=list)
    target_roles: Mapped[list] = mapped_column(JSONB, default=list)
    remote_types: Mapped[list] = mapped_column(JSONB, default=list)
    employment_types: Mapped[list] = mapped_column(JSONB, default=list)

    min_match_score: Mapped[int] = mapped_column(Integer, default=60)
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    posted_within_days: Mapped[int] = mapped_column(Integer, default=30)

    include_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    exclude_keywords: Mapped[list] = mapped_column(JSONB, default=list)

    # Phase 7 execution controls (user-configurable, not hard-coded).
    daily_application_target: Mapped[int | None] = mapped_column(Integer)
    daily_application_maximum: Mapped[int | None] = mapped_column(Integer)
    max_concurrent_executions: Mapped[int | None] = mapped_column(Integer)
    # {"linkedin": "HUMAN_ASSISTED", "indeed": "PERMITTED_BROWSER", ...}
    platform_policies: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Phase 8 follow-up scheduling (central config, applied when an
    # application is first submitted).
    follow_up_interval_days: Mapped[int] = mapped_column(Integer, default=7)
    # Phase 9: thank-you follow-up offset after an interview is scheduled.
    interview_follow_up_days: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
