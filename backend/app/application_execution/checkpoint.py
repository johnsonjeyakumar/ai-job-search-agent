"""Checkpointing and execution recovery (Phase 12).

Saves execution state at every critical step so that if the browser crashes,
network fails, or the process is interrupted, we can resume without restarting
from scratch. Checkpoints are idempotent — replaying them produces the same result.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class CheckpointType(str, Enum):
    """Types of checkpoints."""
    FORM_INSPECTED = "FORM_INSPECTED"
    FIELDS_MAPPED = "FIELDS_MAPPED"
    FIELDS_FILLED = "FIELDS_FILLED"
    QUESTIONS_ANSWERED = "QUESTIONS_ANSWERED"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    HUMAN_APPROVAL_REQUESTED = "HUMAN_APPROVAL_REQUESTED"
    HUMAN_APPROVAL_GRANTED = "HUMAN_APPROVAL_GRANTED"
    SUBMISSION_ATTEMPTED = "SUBMISSION_ATTEMPTED"
    SUBMISSION_CONFIRMED = "SUBMISSION_CONFIRMED"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"
    ERROR_RECOVERED = "ERROR_RECOVERED"
    ABORTED = "ABORTED"


@dataclass
class Checkpoint:
    """A single execution checkpoint."""

    id: int | None = None
    run_id: str = ""
    checkpoint_type: str = ""
    step_number: int = 0
    timestamp: str = ""
    state_snapshot: dict = field(default_factory=dict)
    fields_filled: dict = field(default_factory=dict)
    questions_answered: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    recovered: bool = False
    data_hash: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.data_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute hash of checkpoint data for integrity."""
        data = json.dumps({
            "run_id": self.run_id,
            "checkpoint_type": self.checkpoint_type,
            "step_number": self.step_number,
            "state_snapshot": self.state_snapshot,
            "fields_filled": self.fields_filled,
            "questions_answered": self.questions_answered,
        }, sort_keys=True, default=str)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class CheckpointStore:
    """In-memory checkpoint store.

    In production, this would be backed by a database. For now, it's an
    in-memory implementation that can be easily swapped.
    """

    checkpoints: dict[str, list[Checkpoint]] = field(default_factory=dict)

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        """Save a checkpoint."""
        run_id = checkpoint.run_id
        if run_id not in self.checkpoints:
            self.checkpoints[run_id] = []

        # Assign ID
        checkpoint.id = len(self.checkpoints[run_id]) + 1
        self.checkpoints[run_id].append(checkpoint)
        return checkpoint

    def get_latest(self, run_id: str) -> Checkpoint | None:
        """Get the latest checkpoint for a run."""
        if run_id in self.checkpoints and self.checkpoints[run_id]:
            return self.checkpoints[run_id][-1]
        return None

    def get_by_type(self, run_id: str, checkpoint_type: str) -> list[Checkpoint]:
        """Get checkpoints of a specific type for a run."""
        if run_id not in self.checkpoints:
            return []
        return [
            cp for cp in self.checkpoints[run_id]
            if cp.checkpoint_type == checkpoint_type
        ]

    def get_all(self, run_id: str) -> list[Checkpoint]:
        """Get all checkpoints for a run."""
        return self.checkpoints.get(run_id, [])

    def clear(self, run_id: str) -> None:
        """Clear all checkpoints for a run."""
        self.checkpoints.pop(run_id, None)

    def can_resume(self, run_id: str) -> bool:
        """Check if a run can be resumed from checkpoints."""
        latest = self.get_latest(run_id)
        if not latest:
            return False
        # Can resume if not in terminal state
        return latest.checkpoint_type not in (
            CheckpointType.SUBMISSION_CONFIRMED,
            CheckpointType.SUBMISSION_FAILED,
            CheckpointType.ABORTED,
        )

    def get_resume_point(self, run_id: str) -> dict:
        """Get the state needed to resume from the latest checkpoint."""
        latest = self.get_latest(run_id)
        if not latest:
            return {"can_resume": False}

        return {
            "can_resume": True,
            "last_checkpoint": latest.checkpoint_type,
            "step_number": latest.step_number,
            "fields_filled": latest.fields_filled,
            "questions_answered": latest.questions_answered,
            "state_snapshot": latest.state_snapshot,
        }


# ---------------------------------------------------------------------------
# Checkpoint creation helpers
# ---------------------------------------------------------------------------

def create_form_inspected_checkpoint(
    run_id: str,
    step: int,
    fields_found: int,
    form_url: str,
) -> Checkpoint:
    """Create a checkpoint after form inspection."""
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=CheckpointType.FORM_INSPECTED,
        step_number=step,
        state_snapshot={
            "fields_found": fields_found,
            "form_url": form_url,
        },
    )


def create_fields_mapped_checkpoint(
    run_id: str,
    step: int,
    mapped_fields: dict[str, str],
    warnings: list[str],
) -> Checkpoint:
    """Create a checkpoint after field mapping."""
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=CheckpointType.FIELDS_MAPPED,
        step_number=step,
        state_snapshot={
            "mapped_fields": mapped_fields,
            "warnings": warnings,
        },
    )


def create_fields_filled_checkpoint(
    run_id: str,
    step: int,
    fields_filled: dict[str, str],
    fields_skipped: list[str],
) -> Checkpoint:
    """Create a checkpoint after filling fields."""
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=CheckpointType.FIELDS_FILLED,
        step_number=step,
        fields_filled=fields_filled,
        state_snapshot={
            "fields_skipped": fields_skipped,
        },
    )


def create_questions_answered_checkpoint(
    run_id: str,
    step: int,
    questions_answered: dict[str, str],
    questions_pending: list[str],
) -> Checkpoint:
    """Create a checkpoint after answering questions."""
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=CheckpointType.QUESTIONS_ANSWERED,
        step_number=step,
        questions_answered=questions_answered,
        state_snapshot={
            "questions_pending": questions_pending,
        },
    )


def create_submission_checkpoint(
    run_id: str,
    step: int,
    status: str,
    submission_url: str | None = None,
    confirmation_id: str | None = None,
) -> Checkpoint:
    """Create a checkpoint for submission status."""
    checkpoint_type = (
        CheckpointType.SUBMISSION_CONFIRMED
        if status == "SUCCEEDED"
        else CheckpointType.SUBMISSION_FAILED
        if status == "FAILED"
        else CheckpointType.SUBMISSION_ATTEMPTED
    )
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=checkpoint_type,
        step_number=step,
        state_snapshot={
            "status": status,
            "submission_url": submission_url,
            "confirmation_id": confirmation_id,
        },
    )


def create_human_approval_checkpoint(
    run_id: str,
    step: int,
    action: str,
    fields: list[str],
    reason: str,
) -> Checkpoint:
    """Create a checkpoint for human approval."""
    checkpoint_type = (
        CheckpointType.HUMAN_APPROVAL_GRANTED
        if action == "granted"
        else CheckpointType.HUMAN_APPROVAL_REQUESTED
    )
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=checkpoint_type,
        step_number=step,
        state_snapshot={
            "action": action,
            "fields": fields,
            "reason": reason,
        },
    )


def create_error_checkpoint(
    run_id: str,
    step: int,
    error: str,
    recovered: bool = False,
) -> Checkpoint:
    """Create a checkpoint for error recovery."""
    return Checkpoint(
        run_id=run_id,
        checkpoint_type=(
            CheckpointType.ERROR_RECOVERED if recovered
            else CheckpointType.SUBMISSION_FAILED
        ),
        step_number=step,
        errors=[error],
        recovered=recovered,
    )
