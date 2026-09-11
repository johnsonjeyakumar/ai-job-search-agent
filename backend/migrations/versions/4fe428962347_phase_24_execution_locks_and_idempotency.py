"""Phase 24: execution locks and idempotency

Revision ID: 4fe428962347
Revises: c7d8e9f0a1b2
Create Date: 2026-09-10 21:10:58.282136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4fe428962347'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create execution_locks table
    op.create_table(
        "execution_locks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("package_id", sa.Integer, sa.ForeignKey("application_packages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.Integer, sa.ForeignKey("application_executions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("lock_acquired_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("package_id", name="uq_execution_locks_package"),
    )
    op.create_index("ix_execution_locks_package", "execution_locks", ["package_id"])
    op.create_index("ix_execution_locks_owner", "execution_locks", ["owner_id"])

    # 2. Add idempotency and submission boundary columns to application_executions
    op.add_column("application_executions", sa.Column(
        "idempotency_key", sa.String(255), nullable=True,
    ))
    op.add_column("application_executions", sa.Column(
        "submission_attempted_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("application_executions", sa.Column(
        "retry_authorized_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("application_executions", sa.Column(
        "retry_reason", sa.Text, nullable=True,
    ))

    # 3. Add index on idempotency_key for fast duplicate lookups
    op.create_index(
        "ix_executions_idempotency_key",
        "application_executions",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_executions_idempotency_key", table_name="application_executions")
    op.drop_column("application_executions", "retry_reason")
    op.drop_column("application_executions", "retry_authorized_at")
    op.drop_column("application_executions", "submission_attempted_at")
    op.drop_column("application_executions", "idempotency_key")
    op.drop_index("ix_execution_locks_owner", table_name="execution_locks")
    op.drop_index("ix_execution_locks_package", table_name="execution_locks")
    op.drop_table("execution_locks")
