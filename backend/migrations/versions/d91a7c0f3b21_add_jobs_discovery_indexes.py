"""add jobs discovery indexes

Revision ID: d91a7c0f3b21
Revises: 72c74bb5b6e2
Create Date: 2026-09-05 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d91a7c0f3b21"
down_revision: Union[str, Sequence[str], None] = "72c74bb5b6e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add indexes used by the job discovery filters and ordering."""
    op.create_index("ix_jobs_location", "jobs", ["location"], unique=False)
    op.create_index("ix_jobs_posted_date", "jobs", ["posted_date"], unique=False)
    op.create_index(
        "ix_jobs_discovered_date", "jobs", ["discovered_date"], unique=False
    )


def downgrade() -> None:
    """Drop the discovery indexes."""
    op.drop_index("ix_jobs_discovered_date", table_name="jobs")
    op.drop_index("ix_jobs_posted_date", table_name="jobs")
    op.drop_index("ix_jobs_location", table_name="jobs")