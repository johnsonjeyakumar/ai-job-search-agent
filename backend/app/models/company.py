"""Lightweight company intelligence, derived only from collected job data."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Company(Base):
    """An observed employer, keyed by a deterministic normalized name.

    Only internally-observed facts are stored. Everything else (industry,
    size, revenue, ...) stays NULL until a trustworthy source provides it.
    Aggregates such as active_job_count are computed from the jobs table, not
    stored here.
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_name: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(Text)
    careers_url: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(255))
    company_size: Mapped[str | None] = mapped_column(String(100))
    first_seen_job_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_seen_job_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
