from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Profile(Base):
    """Personal profile used to evaluate and match jobs."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)

    phone: Mapped[str | None] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    portfolio_url: Mapped[str | None] = mapped_column(Text)

    education: Mapped[str | None] = mapped_column(String(255))  # legacy
    degree: Mapped[str | None] = mapped_column(String(255))
    university: Mapped[str | None] = mapped_column(String(255))
    graduation_year: Mapped[int | None] = mapped_column()
    cgpa: Mapped[str | None] = mapped_column(String(50))

    skills: Mapped[list] = mapped_column(JSONB, default=list)  # aggregate
    skills_programming: Mapped[list] = mapped_column(JSONB, default=list)
    skills_frameworks: Mapped[list] = mapped_column(JSONB, default=list)
    skills_databases: Mapped[list] = mapped_column(JSONB, default=list)
    skills_tools: Mapped[list] = mapped_column(JSONB, default=list)
    skills_other: Mapped[list] = mapped_column(JSONB, default=list)
    projects: Mapped[list] = mapped_column(JSONB, default=list)
    internships: Mapped[list] = mapped_column(JSONB, default=list)
    certifications: Mapped[list] = mapped_column(JSONB, default=list)

    experience_level: Mapped[str | None] = mapped_column(String(100))
    preferred_roles: Mapped[list] = mapped_column(JSONB, default=list)
    preferred_locations: Mapped[list] = mapped_column(JSONB, default=list)
    remote_preference: Mapped[str | None] = mapped_column(String(50))
    salary_preference: Mapped[str | None] = mapped_column(String(255))
    notice_period: Mapped[str | None] = mapped_column(String(100))
    work_authorization: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
