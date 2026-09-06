"""Phase 6: application preparation engine

Revision ID: e60a8f4d2c71
Revises: c7e5b2f9a3d4
Create Date: 2026-09-06 12:00:00.000000

Adds the application package tables: ``application_packages`` and its
normalized child tables (evidence, tailoring suggestions, answers, validation
results). Nothing here changes Phase 4/5 behavior and nothing is dropped.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e60a8f4d2c71"
down_revision: Union[str, Sequence[str], None] = "c7e5b2f9a3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 6 application preparation schema."""
    op.create_table(
        "application_packages",
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
        sa.Column(
            "selected_resume_id",
            sa.Integer(),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "readiness",
            sa.String(20),
            nullable=False,
            server_default="NOT_READY",
        ),
        sa.Column("readiness_reasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "quality_gate",
            sa.String(30),
            nullable=False,
            server_default="NEEDS_REVIEW",
        ),
        sa.Column("quality_gate_summary", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=True),
        sa.Column(
            "recommendation", sa.String(20), nullable=False, server_default="REVIEW"
        ),
        sa.Column("resume_selection", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("gap_analysis", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("cover_letter", sa.Text(), nullable=True),
        sa.Column(
            "cover_letter_status",
            sa.String(30),
            nullable=False,
            server_default="skipped",
        ),
        sa.Column("duplicate_disclaimer", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_application_packages_job_id", "application_packages", ["job_id"])
    op.create_index(
        "ix_application_packages_profile_id", "application_packages", ["profile_id"]
    )
    op.create_index(
        "ix_application_packages_selected_resume_id",
        "application_packages",
        ["selected_resume_id"],
    )
    op.create_index("ix_application_packages_status", "application_packages", ["status"])

    op.create_table(
        "application_evidence_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("application_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement", sa.String(500), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="job"),
        sa.Column("confidence", sa.String(10), nullable=False, server_default="LOW"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_application_evidence_package_id", "application_evidence_entries", ["package_id"]
    )

    op.create_table(
        "application_tailoring_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("application_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resume_id",
            sa.Integer(),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("requirement", sa.String(500), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("existing_evidence", sa.Text(), nullable=True),
        sa.Column("suggested_wording", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(10), nullable=False, server_default="LOW"),
        sa.Column(
            "review_status",
            sa.String(30),
            nullable=False,
            server_default="NEEDS_USER_REVIEW",
        ),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_application_tailoring_package_id",
        "application_tailoring_suggestions",
        ["package_id"],
    )
    op.create_index(
        "ix_application_tailoring_resume_id",
        "application_tailoring_suggestions",
        ["resume_id"],
    )

    op.create_table(
        "application_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("application_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("source_evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(10), nullable=False, server_default="LOW"),
        sa.Column(
            "validation_status",
            sa.String(30),
            nullable=False,
            server_default="NEEDS_REVIEW",
        ),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_application_answers_package_id", "application_answers", ["package_id"])

    op.create_table(
        "application_validation_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("application_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.String(50), nullable=False),
        sa.Column("check", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_application_validation_package_id",
        "application_validation_results",
        ["package_id"],
    )


def downgrade() -> None:
    """Remove Phase 6 schema (children first, then the package table)."""
    op.drop_index(
        "ix_application_validation_package_id", table_name="application_validation_results"
    )
    op.drop_table("application_validation_results")
    op.drop_index("ix_application_answers_package_id", table_name="application_answers")
    op.drop_table("application_answers")
    op.drop_index(
        "ix_application_tailoring_resume_id", table_name="application_tailoring_suggestions"
    )
    op.drop_index(
        "ix_application_tailoring_package_id", table_name="application_tailoring_suggestions"
    )
    op.drop_table("application_tailoring_suggestions")
    op.drop_index(
        "ix_application_evidence_package_id", table_name="application_evidence_entries"
    )
    op.drop_table("application_evidence_entries")
    op.drop_index(
        "ix_application_packages_status", table_name="application_packages"
    )
    op.drop_index(
        "ix_application_packages_selected_resume_id", table_name="application_packages"
    )
    op.drop_index(
        "ix_application_packages_profile_id", table_name="application_packages"
    )
    op.drop_index("ix_application_packages_job_id", table_name="application_packages")
    op.drop_table("application_packages")