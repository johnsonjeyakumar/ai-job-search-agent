"""Human approval boundaries (Phase 12).

Defines when the agent MUST stop and ask for human approval before proceeding.
Approval is required for:
- Submitting applications
- Handling CAPTCHAs
- High-sensitivity field auto-fill
- Error recovery that changes answers
- Any destructive action
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ApprovalAction(str, Enum):
    """Actions that require human approval."""
    SUBMIT_APPLICATION = "SUBMIT_APPLICATION"
    HANDLE_CAPTCHA = "HANDLE_CAPTCHA"
    AUTO_FILL_SENSITIVE = "AUTO_FILL_SENSITIVE"
    CHANGE_EXISTING_ANSWER = "CHANGE_EXISTING_ANSWER"
    RECOVER_FROM_ERROR = "RECOVER_FROM_ERROR"
    ABORT_APPLICATION = "ABORT_APPLICATION"
    SKIP_QUESTION = "SKIP_QUESTION"


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


@dataclass
class ApprovalRequest:
    """A request for human approval."""

    id: int | None = None
    run_id: str = ""
    action: str = ""
    status: str = ApprovalStatus.PENDING
    details: dict = field(default_factory=dict)
    reason: str = ""
    created_at: str = ""
    responded_at: str | None = None
    response_notes: str | None = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalPolicy:
    """Policy defining when human approval is required."""

    # Always require approval
    require_approval_for: list[str] = field(default_factory=lambda: [
        ApprovalAction.SUBMIT_APPLICATION,
        ApprovalAction.HANDLE_CAPTCHA,
        ApprovalAction.ABORT_APPLICATION,
    ])

    # Require approval if sensitivity is this level or higher
    sensitivity_threshold: str = "HIGH"

    # Auto-allow for low-sensitivity fields
    auto_allow_low_sensitivity: bool = True

    # Maximum time to wait for approval (seconds)
    approval_timeout: int = 300

    # Allow batch approval for multiple fields
    allow_batch_approval: bool = True


@dataclass
class ApprovalStore:
    """Stores and manages approval requests."""

    requests: dict[str, ApprovalRequest] = field(default_factory=dict)
    policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)

    def request_approval(
        self,
        run_id: str,
        action: str,
        details: dict | None = None,
        reason: str = "",
    ) -> ApprovalRequest:
        """Create an approval request."""
        request = ApprovalRequest(
            run_id=run_id,
            action=action,
            details=details or {},
            reason=reason,
        )
        self.requests[f"{run_id}:{action}"] = request
        return request

    def grant_approval(
        self,
        run_id: str,
        action: str,
        notes: str | None = None,
    ) -> ApprovalRequest | None:
        """Grant approval for a request."""
        key = f"{run_id}:{action}"
        if key in self.requests:
            self.requests[key].status = ApprovalStatus.GRANTED
            self.requests[key].responded_at = datetime.now(timezone.utc).isoformat()
            self.requests[key].response_notes = notes
            return self.requests[key]
        return None

    def deny_approval(
        self,
        run_id: str,
        action: str,
        notes: str | None = None,
    ) -> ApprovalRequest | None:
        """Deny approval for a request."""
        key = f"{run_id}:{action}"
        if key in self.requests:
            self.requests[key].status = ApprovalStatus.DENIED
            self.requests[key].responded_at = datetime.now(timezone.utc).isoformat()
            self.requests[key].response_notes = notes
            return self.requests[key]
        return None

    def is_approved(self, run_id: str, action: str) -> bool:
        """Check if an action is approved."""
        key = f"{run_id}:{action}"
        if key in self.requests:
            return self.requests[key].status == ApprovalStatus.GRANTED
        return False

    def needs_approval(
        self,
        action: str,
        sensitivity: str = "LOW",
    ) -> bool:
        """Check if an action needs human approval based on policy."""
        # Always require for certain actions
        if action in self.policy.require_approval_for:
            return True

        # Check sensitivity threshold
        sensitivity_levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        action_level = sensitivity_levels.get(sensitivity, 0)
        threshold_level = sensitivity_levels.get(self.policy.sensitivity_threshold, 2)

        if action_level >= threshold_level:
            return True

        # Auto-allow low sensitivity
        if sensitivity == "LOW" and self.policy.auto_allow_low_sensitivity:
            return False

        return False

    def get_pending(self, run_id: str) -> list[ApprovalRequest]:
        """Get all pending requests for a run."""
        return [
            req for req in self.requests.values()
            if req.run_id == run_id and req.status == ApprovalStatus.PENDING
        ]

    def clear(self, run_id: str) -> None:
        """Clear all requests for a run."""
        self.requests = {
            k: v for k, v in self.requests.items()
            if v.run_id != run_id
        }


# ---------------------------------------------------------------------------
# Approval flow helpers
# ---------------------------------------------------------------------------

def check_approval_needed(
    action: str,
    sensitivity: str = "LOW",
    policy: ApprovalPolicy | None = None,
) -> tuple[bool, str]:
    """Check if approval is needed and return reason.

    Returns:
        Tuple of (needs_approval, reason).
    """
    policy = policy or ApprovalPolicy()

    if action in policy.require_approval_for:
        return True, f"Action '{action}' always requires human approval."

    sensitivity_levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    action_level = sensitivity_levels.get(sensitivity, 0)
    threshold_level = sensitivity_levels.get(policy.sensitivity_threshold, 2)

    if action_level >= threshold_level:
        return True, (
            f"Field sensitivity '{sensitivity}' meets or exceeds "
            f"threshold '{policy.sensitivity_threshold}'."
        )

    return False, "No approval required."


def create_approval_payload(
    request: ApprovalRequest,
    page_url: str | None = None,
    field_values: dict[str, str] | None = None,
) -> dict:
    """Create a payload for the approval UI."""
    return {
        "request_id": f"{request.run_id}:{request.action}",
        "action": request.action,
        "reason": request.reason,
        "details": request.details,
        "page_url": page_url,
        "field_values": field_values or {},
        "created_at": request.created_at,
        "timeout_seconds": 300,
    }
