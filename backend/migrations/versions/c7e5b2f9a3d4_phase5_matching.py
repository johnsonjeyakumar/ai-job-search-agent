"""Phase 5: personal matching and opportunity decisions

Revision ID: c7e5b2f9a3d4
Revises: a2f9c4e1d3b6
Create Date: 2026-09-06 00:00:00.000000

Adds the Phase 5 matching columns to ``job_matches`` and the new
``opportunity_scores`` table. Nothing here changes Phase 4 behavior.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7e5b2f9a3d4"
down_revision: Union[str, Sequence[str], None] = "a2f9c4e1d3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 5 matching + opportunity schema."""
    # --- job_matches: Phase 5 matching columns -----------------------------
    op.add_column(
        "job_matches",
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "job_matches",
        sa.Column("matching_version", sa.String(20), nullable=True),
    )
    op.add_column(
        "job_matches", sa.Column("context_key", sa.String(64), nullable=True)
    )
    op.add_column(
        "job_matches",
        sa.Column("partial_requirements", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "job_matches",
        sa.Column("matched_requirements", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "job_matches",
        sa.Column("missing_requirements", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "job_matches",
        sa.Column("unknown_requirements", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "job_matches", sa.Column("evidence", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "job_matches",
        sa.Column("explanation", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "job_matches",
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Existing rows predate matching: backfill version/calculated_at then
    # make the columns non-null to match the model.
    op.execute(
        "UPDATE job_matches SET matching_version = 'v1', "
        "calculated_at = COALESCE(calculated_at, created_at) "
        "WHERE matching_version IS NULL"
    )
    op.execute(
        "ALTER TABLE job_matches ALTER COLUMN matching_version "
        "SET DEFAULT 'v1'"
    )
    op.execute(
        "ALTER TABLE job_matches ALTER COLUMN matching_version SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE job_matches ALTER COLUMN calculated_at SET NOT NULL"
    )
    for col in (
        "matched_requirements",
        "partial_requirements",
        "missing_requirements",
        "unknown_requirements",
        "evidence",
        "explanation",
    ):
        op.execute(f"ALTER TABLE job_matches ALTER COLUMN {col} SET DEFAULT '[]'")
        op.execute(f"ALTER TABLE job_matches ALTER COLUMN {col} SET NOT NULL")

    op.create_index("ix_job_matches_matching_version", "job_matches", ["matching_version"])
    op.create_index("ix_job_matches_context_key", "job_matches", ["context_key"])

    # --- opportunity_scores ----------------------------------------------
    op.create_table(
        "opportunity_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("freshness_score", sa.Integer(), nullable=True),
        sa.Column("company_score", sa.Integer(), nullable=True),
        sa.Column("opportunity_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=False),
        sa.Column("opportunity_version", sa.String(20), nullable=True),
        sa.Column("explanation", postgresql.JSONB(), nullable=True),
        sa.Column("blockers", postgresql.JSONB(), nullable=True),
        sa.Column(
            "calculated_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.UniqueConstraint(
            "job_id",
            "profile_id",
            "opportunity_version",
            name="uq_opportunity_scores_job_profile_version",
        ),
    )
    op.create_index(
        "ix_opportunity_scores_job_id", "opportunity_scores", ["job_id"]
    )
    op.create_index(
        "ix_opportunity_scores_profile_id", "opportunity_scores", ["profile_id"]
    )
    op.create_index(
        "ix_opportunity_scores_recommendation",
        "opportunity_scores",
        ["recommendation"],
    )
    op.create_index(
        "ix_opportunity_scores_opportunity_score",
        "opportunity_scores",
        ["opportunity_score"],
    )

    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN opportunity_version SET DEFAULT 'v1'"
    )
    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN opportunity_version SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN explanation SET DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN explanation SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN blockers SET DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN blockers SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE opportunity_scores ALTER COLUMN calculated_at SET NOT NULL"
    )


def downgrade() -> None:
    """Remove Phase 5 schema."""
    op.drop_table("opportunity_scores")
    op.drop_index("ix_job_matches_matching_version", table_name="job_matches")
    op.drop_index("ix_job_matches_context_key", table_name="job_matches")
    op.drop_column("job_matches", "calculated_at")
    op.drop_column("job_matches", "explanation")
    op.drop_column("job_matches", "evidence")
    op.drop_column("job_matches", "unknown_requirements")
    op.drop_column("job_matches", "missing_requirements")
    op.drop_column("job_matches", "matched_requirements")
    op.drop_column("job_matches", "partial_requirements")
    op.drop_column("job_matches", "context_key")
    op.drop_column("job_matches", "matching_version")
    op.drop_column("job_matches", "confidence_score")