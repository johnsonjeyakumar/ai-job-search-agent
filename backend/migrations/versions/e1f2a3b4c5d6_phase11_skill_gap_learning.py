"""Phase 11: skill gap analysis & learning plan tables

Revision ID: e1f2a3b4c5d6
Revises: d4f8a2b1c3e5
Create Date: 2026-09-07 22:00:00.000000

Creates four new tables for skill gap analysis and learning plans:
- skill_gap_analyses: per-job skill gap snapshots
- skill_gap_evidence: evidence entries for skill gaps
- learning_plans: learning plan headers
- learning_items: individual learning tasks within plans
- learning_evidence: evidence attached to learning items

No existing tables are modified.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d4f8a2b1c3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- skill_gap_analyses ---
    op.create_table(
        "skill_gap_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column(
            "resume_id",
            sa.Integer(),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("matched_skills", postgresql.JSONB(), server_default="[]"),
        sa.Column("partial_skills", postgresql.JSONB(), server_default="[]"),
        sa.Column("missing_skills", postgresql.JSONB(), server_default="[]"),
        sa.Column("unknown_skills", postgresql.JSONB(), server_default="[]"),
        sa.Column("evidence", postgresql.JSONB(), server_default="[]"),
        sa.Column("priorities", postgresql.JSONB(), server_default="{}"),
        sa.Column("market_demand", postgresql.JSONB(), server_default="{}"),
        sa.Column("readiness_label", sa.String(50), server_default="UNKNOWN"),
        sa.Column("readiness_percentage", sa.Integer(), server_default="0"),
        sa.Column("readiness_breakdown", postgresql.JSONB(), server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # --- learning_plans ---
    op.create_table(
        "learning_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("target_role", sa.String(255)),
        sa.Column("title", sa.String(500)),
        sa.Column("status", sa.String(20), server_default="NOT_STARTED"),
        sa.Column("total_items", sa.Integer(), server_default="0"),
        sa.Column("completed_items", sa.Integer(), server_default="0"),
        sa.Column("verified_items", sa.Integer(), server_default="0"),
        sa.Column("estimated_effort_hours", sa.Integer(), server_default="0"),
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
    )

    # --- learning_items ---
    op.create_table(
        "learning_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("learning_plans.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("skill", sa.String(255)),
        sa.Column("priority", sa.String(10), server_default="MEDIUM"),
        sa.Column("objective", sa.Text()),
        sa.Column("estimated_hours", sa.Integer(), server_default="0"),
        sa.Column("prerequisites", postgresql.JSONB(), server_default="[]"),
        sa.Column("tasks", postgresql.JSONB(), server_default="[]"),
        sa.Column("completion_criteria", sa.Text()),
        sa.Column("evidence_requirement", sa.Text()),
        sa.Column("status", sa.String(20), server_default="NOT_STARTED"),
        sa.Column("evidence_links", postgresql.JSONB(), server_default="[]"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
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
    )

    # --- learning_evidence ---
    op.create_table(
        "learning_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("learning_items.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("evidence_type", sa.String(50)),
        sa.Column("url", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("learning_evidence")
    op.drop_table("learning_items")
    op.drop_table("learning_plans")
    op.drop_table("skill_gap_analyses")
