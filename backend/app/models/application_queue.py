"""Application queue and autopilot orchestration models.

Queue states are orchestration-only and do not conflict with the application
lifecycle statuses in ``application_tracking``. The queue sits *above* the
existing Phase 7 execution engine: it decides *which* approved packages to
process and in *what order*, then delegates to the existing executor.

Autopilot runs track batch-processing sessions with counters and status.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# ---------------------------------------------------------------------------
# Queue states (orchestration only — never written to applications.lifecycle_status)
# ---------------------------------------------------------------------------
QUEUE_STATES = (
    "QUEUED",
    "PREPARING",
    "READY",
    "NEEDS_INPUT",
    "REVIEW",
    "BLOCKED",
    "APPROVED",
    "EXECUTING",
    "SUBMITTED",
    "FAILED",
    "SKIPPED",
    "COMPLETED",
)

# Attention categories derived from queue state.
ATTENTION_AUTO = "AUTO"
ATTENTION_ASK = "ASK"
ATTENTION_REVIEW = "REVIEW"
ATTENTION_BLOCK = "BLOCK"

# ---------------------------------------------------------------------------
# Autopilot run states
# ---------------------------------------------------------------------------
AUTOPILOT_STATES = (
    "IDLE",
    "RUNNING",
    "PAUSED",
    "COMPLETED",
    "FAILED",
)


class ApplicationQueueItem(Base):
    """One item in the application processing queue.

    Each row represents a matched job + approved package that is waiting to be
    processed. ``queue_state`` is the orchestration state; it moves through
    preflight -> attention classification -> execution -> completion.

    ``priority_score`` is deterministic: a weighted blend of personal match,
    opportunity, quality, and freshness — never LLM-generated.
    """

    __tablename__ = "application_queue_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    package_id: Mapped[int] = mapped_column(
        ForeignKey("application_packages.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    # Orchestration state — distinct from application lifecycle_status.
    queue_state: Mapped[str] = mapped_column(
        String(30), default="QUEUED", index=True
    )
    # Attention category: AUTO | ASK | REVIEW | BLOCK (set after preflight).
    attention: Mapped[str | None] = mapped_column(String(20), index=True)
    # Why the item needs attention (populated when attention != AUTO).
    attention_reason: Mapped[str | None] = mapped_column(Text)
    # Deterministic priority score (higher = process first).
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    # Snapshot of scores at queue time (for display + audit).
    match_score: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)
    freshness_score: Mapped[float | None] = mapped_column(Float)
    # Job + company snapshots for display.
    job_title: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(50))
    # Resume snapshot for display.
    resume_name: Mapped[str | None] = mapped_column(String(255))
    # Linked execution (set once execution starts).
    execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_executions.id", ondelete="SET NULL")
    )
    # Linked autopilot run (set when autopilot picks up this item).
    autopilot_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("autopilot_runs.id", ondelete="SET NULL")
    )
    # User-supplied resolution for NEEDS_INPUT items (JSON dict).
    resolution_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Skip reason (if user skips this item).
    skip_reason: Mapped[str | None] = mapped_column(Text)
    # Error message if processing failed.
    error_message: Mapped[str | None] = mapped_column(Text)
    # Ordering within the same priority (lower = first).
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Timestamps.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutopilotRun(Base):
    """Tracks a batch autopilot processing session.

    An autopilot run picks up queued items in priority order, runs preflight,
    and either auto-processes or routes to attention states. The run is
    interruptible (pause/resume/stop).
    """

    __tablename__ = "autopilot_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        String(20), default="IDLE", index=True
    )
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    submitted_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    input_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    # Current item being processed (for live UI display).
    current_queue_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_queue_items.id", ondelete="SET NULL")
    )
    # Error message if the run itself failed.
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
