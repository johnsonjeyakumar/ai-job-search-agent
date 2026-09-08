"""Skill gap analysis and learning plan models (Phase 11).

Deterministic, evidence-based skill gap analysis. No ML, no prediction.
Every classification is explainable and traceable to stored evidence.
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

SKILL_STATUSES = ("MATCHED", "PARTIAL", "MISSING", "UNKNOWN")
SKILL_CONFIDENCES = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
SKILL_PRIORITIES = ("HIGH", "MEDIUM", "LOW")
LEARNING_STATUSES = (
    "NOT_STARTED",
    "IN_PROGRESS",
    "PRACTICING",
    "COMPLETED",
    "VERIFIED",
)
EVIDENCE_TYPES = (
    "PROFILE",
    "RESUME",
    "PROJECT",
    "INTERNSHIP",
    "CERTIFICATION",
    "INTERVIEW",
    "USER_VERIFIED",
    "JOB_REQUIREMENT",
)


class SkillGapAnalysis(Base):
    """Per-job skill gap analysis snapshot."""

    __tablename__ = "skill_gap_analyses"

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
    matched_skills: Mapped[list] = mapped_column(JSONB, default=list)
    partial_skills: Mapped[list] = mapped_column(JSONB, default=list)
    missing_skills: Mapped[list] = mapped_column(JSONB, default=list)
    unknown_skills: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    priorities: Mapped[dict] = mapped_column(JSONB, default=dict)
    market_demand: Mapped[dict] = mapped_column(JSONB, default=dict)
    readiness_label: Mapped[str] = mapped_column(String(50), default="UNKNOWN")
    readiness_percentage: Mapped[int] = mapped_column(Integer, default=0)
    readiness_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LearningPlan(Base):
    """Learning plan for a target job or role."""

    __tablename__ = "learning_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    target_role: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    verified_items: Mapped[int] = mapped_column(Integer, default=0)
    estimated_effort_hours: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LearningItem(Base):
    """Individual learning item within a plan."""

    __tablename__ = "learning_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True
    )
    skill: Mapped[str] = mapped_column(String(255))
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    objective: Mapped[str] = mapped_column(Text)
    estimated_hours: Mapped[int] = mapped_column(Integer, default=0)
    prerequisites: Mapped[list] = mapped_column(JSONB, default=list)
    tasks: Mapped[list] = mapped_column(JSONB, default=list)
    completion_criteria: Mapped[str | None] = mapped_column(Text)
    evidence_requirement: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="NOT_STARTED")
    evidence_links: Mapped[list] = mapped_column(JSONB, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LearningEvidence(Base):
    """Evidence attached to a learning item for verification."""

    __tablename__ = "learning_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("learning_items.id", ondelete="CASCADE"), index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Controlled vocabularies for new models
# ---------------------------------------------------------------------------

RESOURCE_TYPES = (
    "DOCUMENTATION",
    "TUTORIAL",
    "COURSE",
    "VIDEO",
    "ARTICLE",
    "PRACTICE",
    "PROJECT",
)
RESOURCE_SOURCES = ("USER", "AI_SUGGESTED")
FREE_OR_PAID = ("FREE", "PAID", "UNKNOWN")
DIFFICULTY_LEVELS = ("BEGINNER", "INTERMEDIATE", "ADVANCED", "UNKNOWN")


class LearningResource(Base):
    """A learning resource linked to a learning item."""

    __tablename__ = "learning_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("learning_items.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    resource_type: Mapped[str] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    free_or_paid: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    difficulty: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    source: Mapped[str] = mapped_column(String(20), default="USER")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SkillHistory(Base):
    """Immutable history record for skill/learning state changes."""

    __tablename__ = "skill_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    skill: Mapped[str] = mapped_column(String(255), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(50))
    new_status: Mapped[str] = mapped_column(String(50))
    previous_confidence: Mapped[str | None] = mapped_column(String(20))
    new_confidence: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
