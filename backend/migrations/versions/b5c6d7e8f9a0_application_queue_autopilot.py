"""Application queue and autopilot orchestration tables

Revision ID: b5c6d7e8f9a0
Revises: f2a3b4c5d6e7
Create Date: 2026-09-11 12:00:00.000000

Adds:
- autopilot_runs: batch processing session tracking
- application_queue_items: orchestration queue for approved packages

Circular FKs (autopilot_run_id, current_queue_item_id) are added after both
tables exist.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create autopilot_runs FIRST (no FK to queue yet).
    op.create_table(
        "autopilot_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="IDLE",
        ),
        sa.Column(
            "target_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "processed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "submitted_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "blocked_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "review_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "input_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "skipped_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # FK to queue added after queue table exists.
        sa.Column(
            "current_queue_item_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_autopilot_status",
        "autopilot_runs",
        ["status"],
    )

    # Create application_queue_items (FK to autopilot_runs is deferred).
    op.create_table(
        "application_queue_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("application_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "queue_state",
            sa.String(30),
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column("attention", sa.String(20), nullable=True),
        sa.Column("attention_reason", sa.Text(), nullable=True),
        sa.Column(
            "priority_score",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("freshness_score", sa.Float(), nullable=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("platform", sa.String(50), nullable=True),
        sa.Column("resume_name", sa.String(255), nullable=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("application_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # FK to autopilot_runs added after both tables exist.
        sa.Column(
            "autopilot_run_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "resolution_data",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "position",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_queue_state_priority",
        "application_queue_items",
        ["queue_state", "priority_score"],
    )
    op.create_index(
        "ix_queue_attention",
        "application_queue_items",
        ["attention"],
    )
    op.create_index(
        "ix_queue_job",
        "application_queue_items",
        ["job_id"],
    )

    # Now add the deferred circular FKs.
    op.create_foreign_key(
        "fk_queue_autopilot_run",
        "application_queue_items",
        "autopilot_runs",
        ["autopilot_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_autopilot_current_item",
        "autopilot_runs",
        "application_queue_items",
        ["current_queue_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_table("application_queue_items")
    op.drop_table("autopilot_runs")
