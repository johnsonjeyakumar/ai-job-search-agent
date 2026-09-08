"""Phase 11.1: learning resources & skill history tables

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-08 10:00:00.000000

Adds two new tables for Phase 11.1 enhancements:
- learning_resources: resources linked to learning items
- skill_history: immutable skill state change records

No existing tables are modified.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- learning_resources ---
    op.create_table(
        "learning_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("learning_items.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("provider", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("free_or_paid", sa.String(20), server_default="UNKNOWN"),
        sa.Column("difficulty", sa.String(20), server_default="UNKNOWN"),
        sa.Column("source", sa.String(20), server_default="USER"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # --- skill_history ---
    op.create_table(
        "skill_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("skill", sa.String(255), nullable=False, index=True),
        sa.Column("previous_status", sa.String(50)),
        sa.Column("new_status", sa.String(50), nullable=False),
        sa.Column("previous_confidence", sa.String(20)),
        sa.Column("new_confidence", sa.String(20)),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("skill_history")
    op.drop_table("learning_resources")
