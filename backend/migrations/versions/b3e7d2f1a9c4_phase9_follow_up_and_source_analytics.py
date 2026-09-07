"""Phase 9: follow-up automation engine + resume & job-source analytics

Revision ID: b3e7d2f1a9c4
Revises: a1b2c3d4e5f6
Create Date: 2026-09-07 16:00:00.000000

Extends the follow-up model with deterministic engineering fields
(priority / reason / trigger / dedupe key / skipped_at), adds the application
submission-source column (distinct from the job discovery source), adds the
interview thank-you offset preference, and backfills ``application_source``
only where a real submission platform was recorded by an execution. Nothing is
ever fabricated: rows without a known platform stay NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e7d2f1a9c4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- applications: submission source (distinct from job discovery source).
    op.add_column(
        "applications",
        sa.Column("application_source", sa.String(100), nullable=True),
    )

    # Backfill only real, recorded platforms from the first confirmed execution
    # per job (DISTINCT ON picks the earliest execution id). Rows with no such
    # execution (e.g. manually applied legacy apps) stay NULL.
    op.execute(
        """
        UPDATE applications a
        SET application_source = sub.platform
        FROM (
            SELECT DISTINCT ON (p.job_id) p.job_id, e.platform
            FROM application_executions e
            JOIN application_packages p ON p.id = e.package_id
            WHERE e.status IN ('SUBMITTED', 'SUBMISSION_CONFIRMED')
              AND e.platform IS NOT NULL
            ORDER BY p.job_id, e.id
        ) sub
        WHERE sub.job_id = a.job_id
          AND a.application_source IS NULL
        """
    )
    op.create_index(
        "ix_applications_application_source", "applications", ["application_source"]
    )

    # --- follow_ups: deterministic engineering fields.
    op.add_column("follow_ups", sa.Column("priority", sa.String(10), nullable=True))
    op.add_column("follow_ups", sa.Column("reason", sa.String(50), nullable=True))
    op.add_column(
        "follow_ups", sa.Column("trigger_status", sa.String(40), nullable=True)
    )
    op.add_column("follow_ups", sa.Column("trigger_key", sa.String(100), nullable=True))
    op.add_column(
        "follow_ups",
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_follow_ups_trigger_key", "follow_ups", ["trigger_key"])

    # --- preferences: interview thank-you offset.
    op.add_column(
        "preferences",
        sa.Column(
            "interview_follow_up_days", sa.Integer(), nullable=False, server_default="1"
        ),
    )


def downgrade() -> None:
    op.drop_column("preferences", "interview_follow_up_days")

    op.drop_index("ix_follow_ups_trigger_key", table_name="follow_ups")
    op.drop_column("follow_ups", "skipped_at")
    op.drop_column("follow_ups", "trigger_key")
    op.drop_column("follow_ups", "trigger_status")
    op.drop_column("follow_ups", "reason")
    op.drop_column("follow_ups", "priority")

    op.drop_index("ix_applications_application_source", table_name="applications")
    op.drop_column("applications", "application_source")