"""Phase 4: job intelligence tables and lifecycle timestamps

Revision ID: a2f9c4e1d3b6
Revises: d91a7c0f3b21
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f9c4e1d3b6"
down_revision: Union[str, Sequence[str], None] = "d91a7c0f3b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 4 intelligence schema and backfill lifecycle timestamps."""
    # --- jobs lifecycle timestamps ----------------------------------------
    op.add_column(
        "jobs",
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])

    # Existing jobs are pre-Phase-4: the safest honest timestamp we hold is
    # their discovery date, so both lifecycle bounds start there.
    op.execute(
        "UPDATE jobs SET first_seen_at = discovered_date, "
        "last_seen_at = discovered_date WHERE first_seen_at IS NULL"
    )

    # --- companies --------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("careers_url", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("company_size", sa.String(length=100), nullable=True),
        sa.Column(
            "first_seen_job_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_seen_job_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_companies_normalized_name",
        "companies",
        ["normalized_name"],
        unique=True,
    )
    op.create_index(
        "ix_companies_last_seen_job_at", "companies", ["last_seen_job_at"]
    )

    # --- job_events -------------------------------------------------------
    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_data", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_index("ix_job_events_event_type", "job_events", ["event_type"])
    op.create_index("ix_job_events_created_at", "job_events", ["created_at"])

    # --- job_quality_scores -----------------------------------------------
    op.create_table(
        "job_quality_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("freshness_score", sa.Integer(), nullable=True),
        sa.Column("description_score", sa.Integer(), nullable=True),
        sa.Column("requirements_score", sa.Integer(), nullable=True),
        sa.Column("application_score", sa.Integer(), nullable=True),
        sa.Column("company_score", sa.Integer(), nullable=True),
        sa.Column("location_score", sa.Integer(), nullable=True),
        sa.Column("salary_score", sa.Integer(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("scoring_version", sa.String(length=20), nullable=False),
        sa.Column("explanation", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "job_id",
            "scoring_version",
            name="uq_job_quality_scores_job_version",
        ),
    )
    op.create_index(
        "ix_job_quality_scores_job_id", "job_quality_scores", ["job_id"]
    )
    op.create_index(
        "ix_job_quality_scores_overall_score",
        "job_quality_scores",
        ["overall_score"],
    )


def downgrade() -> None:
    """Drop Phase 4 intelligence schema and lifecycle timestamps."""
    op.drop_index(
        "ix_job_quality_scores_overall_score", table_name="job_quality_scores"
    )
    op.drop_index(
        "ix_job_quality_scores_job_id", table_name="job_quality_scores"
    )
    op.drop_table("job_quality_scores")

    op.drop_index("ix_job_events_created_at", table_name="job_events")
    op.drop_index("ix_job_events_event_type", table_name="job_events")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")

    op.drop_index("ix_companies_last_seen_job_at", table_name="companies")
    op.drop_index(
        "ix_companies_normalized_name", table_name="companies"
    )
    op.drop_table("companies")

    op.drop_index("ix_jobs_last_seen_at", table_name="jobs")
    op.drop_column("jobs", "last_seen_at")
    op.drop_column("jobs", "first_seen_at")