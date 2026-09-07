"""Application lifecycle state machine (Phase 8).

A controlled vocabulary + explicit transition graph. Arbitrary status strings
are never allowed: every status must be in ``TRACKING_STATUSES`` and every
automatic move must be a legal edge in ``TRANSITIONS``.

Nonsensical transitions (e.g. REJECTED -> INTERVIEW) are NOT legal. Manual
correction is only possible through ``override=True`` in the lifecycle service,
which writes a ``STATUS_CORRECTED`` event instead of silently changing state.
"""
from __future__ import annotations

from app.models.application_tracking import TRACKING_STATUSES  # noqa: F401

# ---------------------------------------------------------------------------
# Milestone -> canonical event_type written when the application enters it.
# ---------------------------------------------------------------------------
DEFAULT_EVENT_FOR_STATUS = {
    "DISCOVERED": "APPLICATION_CREATED",
    "SHORTLISTED": "SHORTLISTED",
    "PREPARING": "PACKAGE_PREPARED",
    "READY_FOR_REVIEW": "PACKAGE_READY_FOR_REVIEW",
    "APPROVED": "APPROVED",
    "EXECUTION_READY": "EXECUTION_READY",
    "EXECUTING": "EXECUTION_STARTED",
    "SUBMITTED": "SUBMITTED",
    "SUBMISSION_CONFIRMED": "SUBMISSION_CONFIRMED",
    "RESPONSE_RECEIVED": "RESPONSE_RECEIVED",
    "INTERVIEW": "INTERVIEW_SCHEDULED",
    "OFFER": "OFFER_RECEIVED",
    "REJECTED": "REJECTED",
    "WITHDRAWN": "WITHDRAWN",
    "EXPIRED": "EXPIRED",
    "CANCELLED": "CANCELLED",
}

# Statuses considered "submitted" for denominator purposes.
SUBMITTED_STATUSES = frozenset(
    {"SUBMITTED", "SUBMISSION_CONFIRMED", "RESPONSE_RECEIVED", "INTERVIEW", "OFFER"}
)

# Terminal statuses: no further automatic transitions (manual override only).
_TERMINAL = frozenset({"REJECTED", "WITHDRAWN", "EXPIRED", "CANCELLED", "OFFER"})

# ---------------------------------------------------------------------------
# Explicit transition graph.
# ---------------------------------------------------------------------------
TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERED": frozenset({"SHORTLISTED", "WITHDRAWN", "EXPIRED", "CANCELLED"}),
    "SHORTLISTED": frozenset({"PREPARING", "WITHDRAWN", "EXPIRED", "CANCELLED"}),
    "PREPARING": frozenset({"READY_FOR_REVIEW", "SHORTLISTED", "CANCELLED"}),
    "READY_FOR_REVIEW": frozenset({"APPROVED", "PREPARING", "CANCELLED"}),
    "APPROVED": frozenset({"EXECUTION_READY", "READY_FOR_REVIEW", "CANCELLED"}),
    "EXECUTION_READY": frozenset({"EXECUTING", "CANCELLED"}),
    "EXECUTING": frozenset(
        {"EXECUTION_READY", "SUBMITTED", "SUBMISSION_CONFIRMED", "CANCELLED"}
    ),
    "SUBMITTED": frozenset(
        {"SUBMISSION_CONFIRMED", "RESPONSE_RECEIVED", "REJECTED", "WITHDRAWN", "EXPIRED"}
    ),
    "SUBMISSION_CONFIRMED": frozenset(
        {"RESPONSE_RECEIVED", "REJECTED", "WITHDRAWN", "EXPIRED"}
    ),
    "RESPONSE_RECEIVED": frozenset(
        {"INTERVIEW", "REJECTED", "OFFER", "WITHDRAWN", "EXPIRED"}
    ),
    "INTERVIEW": frozenset(
        {"RESPONSE_RECEIVED", "OFFER", "REJECTED", "WITHDRAWN", "EXPIRED"}
    ),
    "OFFER": frozenset({"WITHDRAWN", "EXPIRED"}),
    "REJECTED": frozenset(),
    "WITHDRAWN": frozenset(),
    "EXPIRED": frozenset(),
    "CANCELLED": frozenset(),
}

_ALL_STATUSES = frozenset(TRACKING_STATUSES)

# Milestones used by the funnel (in order).
FUNNEL_STEPS = (
    "DISCOVERED",
    "SHORTLISTED",
    "PREPARING",
    "READY_FOR_REVIEW",
    "APPROVED",
    "SUBMITTED",
    "SUBMISSION_CONFIRMED",
    "RESPONSE_RECEIVED",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
)


class InvalidStatusError(Exception):
    """A status string is not part of the controlled vocabulary."""

    def __init__(self, value: str):
        super().__init__(f"Invalid application status: {value!r}")
        self.value = value


class IllegalTransitionError(Exception):
    """A transition is not a legal edge in the application state machine."""

    def __init__(self, current: str, target: str):
        super().__init__(
            f"Illegal transition {current} -> {target}. "
            "Use override to record a manual correction (writes a STATUS_CORRECTED event)."
        )
        self.current = current
        self.target = target


def is_valid_status(value: str) -> bool:
    return value in _ALL_STATUSES


def is_terminal(status: str) -> bool:
    return status in _TERMINAL


def can_transition(current: str, target: str) -> bool:
    """Whether ``current -> target`` is a legal edge (no override)."""
    if not is_valid_status(current) or not is_valid_status(target):
        return False
    if current == target:
        return True
    return target in TRANSITIONS.get(current, frozenset())


def default_event_for_status(status: str) -> str:
    return DEFAULT_EVENT_FOR_STATUS.get(status, "STATUS_CORRECTED")


def validate_target_status(target: str) -> None:
    if not is_valid_status(target):
        raise InvalidStatusError(target)
