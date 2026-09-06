"""Phase 7: application execution engine

Revision ID: f7a3b9c2d1e5
Revises: e60a8f4d2c71
Create Date: 2026-09-06 14:00:00.000000

Adds the execution schema (``application_executions``, execution steps,
execution evidence) plus user-configurable execution controls on the
preferences table (daily budget + per-platform policy modes). Nothing drops or
re-writes Phase 4/5/6 behavior.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f7a3b9c2d1e5"
down_revision: Union[str, Sequence[str], None] = "e60a8f4d2c71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 7 execution schema."""
    op.create_table(
        "application_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("application_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column(
            "execution_mode",
            sa.String(30),
            nullable=False,
            server_default="HUMAN_ASSISTED",
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="EXECUTION_READY",
        ),
        sa.Column("current_step", sa.String(60), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_status", sa.String(30), nullable=True),
        sa.Column("confirmation_url", sa.Text(), nullable=True),
        sa.Column("confirmation_reference", sa.String(255), nullable=True),
        sa.Column("approval_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("execution_summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("daily_budget", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_executions_package_id", "application_executions", ["package_id"]
    )
    op.create_index("ix_application_executions_status", "application_executions", ["status"])

    op.create_table(
        "application_execution_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("application_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step", sa.String(60), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_application_execution_steps_execution_id",
        "application_execution_steps",
        ["execution_id"],
    )

    op.create_table(
        "application_execution_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("application_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_application_execution_evidence_execution_id",
        "application_execution_evidence",
        ["execution_id"],
    )

    op.add_column(
        "preferences",
        sa.Column("daily_application_target", sa.Integer(), nullable=True),
    )
    op.add_column(
        "preferences",
        sa.Column("daily_application_maximum", sa.Integer(), nullable=True),
    )
    op.add_column(
        "preferences",
        sa.Column("platform_policies", postgresql.JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    """Remove Phase 7 schema."""
    op.drop_column("preferences", "platform_policies")
    op.drop_column("preferences", "daily_application_maximum")
    op.drop_column("preferences", "daily_application_target")
    op.drop_index(
        "ix_application_execution_evidence_execution_id",
        table_name="application_execution_evidence",
    )
    op.drop_table("application_execution_evidence")
    op.drop_index(
        "ix_application_execution_steps_execution_id",
        table_name="application_execution_steps",
    )
    op.drop_table("application_execution_steps")
    op.drop_index(
        "ix_application_executions_status", table_name="application_executions"
    )
    op.drop_index(
        "ix_application_executions_package_id", table_name="application_executions"
    )
    op.drop_table("application_executions")