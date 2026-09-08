"""Add max_concurrent_executions to preferences

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-09-12 12:00:00.000000

Adds max_concurrent_executions column to preferences table.
This is separate from daily_application_target and daily_application_maximum.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "preferences",
        sa.Column(
            "max_concurrent_executions",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("preferences", "max_concurrent_executions")
