"""Phase 10: interview preparation & interview agent tables

Revision ID: d4f8a2b1c3e5
Revises: b3e7d2f1a9c4
Create Date: 2026-09-07 18:00:00.000000

Creates four new tables for the interview preparation workspace:
- interviews: comprehensive interview records with status, outcome, interviewer
- interview_questions: generated or user-created interview questions
- interview_sessions: mock interview sessions with answers and evaluation
- interview_prep_items: preparation plan checklist items

No existing tables are modified. Phase 8 InterviewRecord is preserved for
backward compatibility.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4f8a2b1c3e5"
down_revision: Union[str, Sequence[str], None] = "b3e7d2f1a9c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- interviews ---
    op.create_table(
        "interviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interview_type", sa.String(40), server_default="OTHER"),
        sa.Column("round", sa.Integer(), server_default="1"),
        sa.Column("interviewer_name", sa.String(255), nullable=True),
        sa.Column("interviewer_role", sa.String(255), nullable=True),
        sa.Column("meeting_url", sa.Text(), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), server_default="SCHEDULED"),
        sa.Column("outcome", sa.String(30), server_default="PENDING"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "feedback_json",
            postgresql.JSONB(),
            server_default="{}",
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
    )

    # --- interview_questions ---
    op.create_table(
        "interview_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "interview_id",
            sa.Integer(),
            sa.ForeignKey("interviews.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(30), server_default="TECHNICAL"),
        sa.Column("difficulty", sa.String(10), server_default="MEDIUM"),
        sa.Column("priority", sa.String(10), server_default="MEDIUM"),
        sa.Column("source", sa.String(30), server_default="GENERAL"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_context", sa.Text(), nullable=True),
        sa.Column("draft_answer", sa.Text(), nullable=True),
        sa.Column(
            "answer_feedback",
            postgresql.JSONB(),
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # --- interview_sessions ---
    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "interview_id",
            sa.Integer(),
            sa.ForeignKey("interviews.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(),
            server_default="{}",
        ),
        sa.Column(
            "questions",
            postgresql.JSONB(),
            server_default="[]",
        ),
        sa.Column(
            "answers",
            postgresql.JSONB(),
            server_default="[]",
        ),
        sa.Column(
            "feedback",
            postgresql.JSONB(),
            server_default="{}",
        ),
        sa.Column(
            "final_summary",
            postgresql.JSONB(),
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # --- interview_prep_items ---
    op.create_table(
        "interview_prep_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "interview_id",
            sa.Integer(),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), server_default="TODO"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("interview_prep_items")
    op.drop_table("interview_sessions")
    op.drop_table("interview_questions")
    op.drop_table("interviews")
