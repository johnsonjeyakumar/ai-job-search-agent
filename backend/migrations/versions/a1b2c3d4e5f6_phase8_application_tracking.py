"""Phase 8: application tracking, timeline & funnel analytics

Revision ID: a1b2c3d4e5f6
Revises: f7a3b9c2d1e5
Create Date: 2026-09-07 12:00:00.000000

Adds the controlled application-lifecycle column (``lifecycle_status``),
immutable history (``application_events``), structured response / interview /
offer records, follow-up scheduling columns, the central follow-up interval on
preferences, and backfills legacy rows so the funnel is computed from the same
timeline model as new data. Nothing fabricates outcomes: the backfill only
mirrors values that already existed in the legacy tracker.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f7a3b9c2d1e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Legacy `applications.status` short forms -> Phase 8 controlled vocabulary.
_LEGACY_TO_LIFECYCLE = {
    "discovered": "DISCOVERED",
    "saved": "SHORTLISTED",
    "preparing": "PREPARING",
    "approved": "APPROVED",
    "applying": "EXECUTING",
    "applied": "SUBMITTED",
    "submitted": "SUBMISSION_CONFIRMED",
    "responded": "RESPONSE_RECEIVED",
    "interviewing": "INTERVIEW",
    "offered": "OFFER",
    "rejected": "REJECTED",
    "withdrawn": "WITHDRAWN",
    "expired": "EXPIRED",
    "cancelled": "CANCELLED",
}


def upgrade() -> None:
    """Add Phase 8 tracking schema."""
    # --- applications: controlled lifecycle column + resume snapshot ----------
    op.add_column(
        "applications",
        sa.Column(
            "lifecycle_status",
            sa.String(40),
            nullable=False,
            server_default="DISCOVERED",
        ),
    )
    op.add_column("applications", sa.Column("resume_name", sa.String(255), nullable=True))
    op.add_column("applications", sa.Column("resume_version", sa.String(50), nullable=True))

    legacy_sql = " ".join(
        f"WHEN '{key}' THEN '{value}'"
        for key, value in _LEGACY_TO_LIFECYCLE.items()
    )
    op.execute(
        f"""
        UPDATE applications
        SET lifecycle_status = CASE status {legacy_sql} ELSE 'DISCOVERED' END
        WHERE lifecycle_status = 'DISCOVERED'
           OR  lifecycle_status IS NULL
        """
    )

    op.create_index("ix_applications_lifecycle_status", "applications", ["lifecycle_status"])
    op.create_index("ix_applications_applied_date", "applications", ["applied_date"])

    # --- follow_ups: scheduling support --------------------------------------
    op.add_column("follow_ups", sa.Column("reminder_date", sa.Date(), nullable=True))
    op.add_column(
        "follow_ups",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- preferences: central follow-up interval -------------------------------
    op.add_column(
        "preferences",
        sa.Column(
            "follow_up_interval_days", sa.Integer(), nullable=False, server_default="7"
        ),
    )

    # --- immutable event history -----------------------------------------------
    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("previous_status", sa.String(40), nullable=True),
        sa.Column("new_status", sa.String(40), nullable=True),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(20), nullable=False, server_default="USER"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_application_events_application_id", "application_events", ["application_id"])
    op.create_index("ix_application_events_event_type", "application_events", ["event_type"])
    op.create_index("ix_application_events_event_timestamp", "application_events", ["event_timestamp"])

    # --- structured records -----------------------------------------------------
    op.create_table(
        "application_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("received_at", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_application_responses_application_id", "application_responses", ["application_id"])
    op.create_index("ix_application_responses_received_at", "application_responses", ["received_at"])

    op.create_table(
        "interview_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interview_date", sa.Date(), nullable=False),
        sa.Column("interview_type", sa.String(40), nullable=False, server_default="OTHER"),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="SCHEDULED"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_interview_records_application_id", "interview_records", ["application_id"])
    op.create_index("ix_interview_records_interview_date", "interview_records", ["interview_date"])

    op.create_table(
        "offer_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offer_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="RECEIVED"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_offer_records_application_id", "offer_records", ["application_id"])
    op.create_index("ix_offer_records_offer_date", "offer_records", ["offer_date"])

    # --- backfill immutable history for legacy tracker rows ---------------------
    # Only mirrors already-known facts (row existed; submission date known).
    # Never fabricates outcomes after submission.
    op.execute(
        """
        INSERT INTO application_events
            (application_id, event_type, previous_status, new_status,
             event_timestamp, source, notes, metadata, created_at)
        SELECT a.id, 'APPLICATION_CREATED', NULL, 'DISCOVERED',
               a.created_at, 'IMPORT',
               'Backfilled from legacy application row.',
               '{"backfill": true}'::jsonb, a.created_at
        FROM applications a
        WHERE NOT EXISTS (
            SELECT 1 FROM application_events e
            WHERE e.application_id = a.id AND e.event_type = 'APPLICATION_CREATED'
        )
        """
    )
    op.execute(
        """
        INSERT INTO application_events
            (application_id, event_type, previous_status, new_status,
             event_timestamp, source, notes, metadata, created_at)
        SELECT a.id,
               CASE WHEN a.lifecycle_status = 'SUBMISSION_CONFIRMED'
                    THEN 'SUBMISSION_CONFIRMED' ELSE 'SUBMITTED' END,
               'DISCOVERED',
               a.lifecycle_status,
               a.applied_date::timestamp,
               'IMPORT',
               'Backfilled submission from legacy application row.',
               '{"backfill": true}'::jsonb, a.created_at
        FROM applications a
        WHERE a.applied_date IS NOT NULL
          AND a.lifecycle_status IN ('SUBMITTED', 'SUBMISSION_CONFIRMED')
          AND NOT EXISTS (
            SELECT 1 FROM application_events e
            WHERE e.application_id = a.id
              AND e.event_type IN ('SUBMITTED', 'SUBMISSION_CONFIRMED')
        )
        """
    )


def downgrade() -> None:
    """Remove Phase 8 tracking schema."""
    op.drop_index("ix_offer_records_offer_date", table_name="offer_records")
    op.drop_index("ix_offer_records_application_id", table_name="offer_records")
    op.drop_table("offer_records")

    op.drop_index("ix_interview_records_interview_date", table_name="interview_records")
    op.drop_index("ix_interview_records_application_id", table_name="interview_records")
    op.drop_table("interview_records")

    op.drop_index("ix_application_responses_received_at", table_name="application_responses")
    op.drop_index("ix_application_responses_application_id", table_name="application_responses")
    op.drop_table("application_responses")

    op.drop_index("ix_application_events_event_timestamp", table_name="application_events")
    op.drop_index("ix_application_events_event_type", table_name="application_events")
    op.drop_index("ix_application_events_application_id", table_name="application_events")
    op.drop_table("application_events")

    op.drop_column("preferences", "follow_up_interval_days")

    op.drop_column("follow_ups", "completed_at")
    op.drop_column("follow_ups", "reminder_date")

    op.drop_index("ix_applications_applied_date", table_name="applications")
    op.drop_index("ix_applications_lifecycle_status", table_name="applications")
    op.drop_column("applications", "resume_version")
    op.drop_column("applications", "resume_name")
    op.drop_column("applications", "lifecycle_status")