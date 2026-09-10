"""Submission verification and outcome intelligence (Phase 19).

Distinguishes deterministic submission outcomes from uncertain ones.
Never assumes that clicking "Submit" means success. Never fabricates
confirmation evidence or reference IDs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

# ---------------------------------------------------------------------------
# Submission outcome model
# ---------------------------------------------------------------------------

class SubmissionOutcome(str, Enum):
    """Deterministic post-submission outcomes."""

    SUBMIT_ATTEMPTED = "SUBMIT_ATTEMPTED"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_CONFIRMED = "SUBMISSION_CONFIRMED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    BLOCKED = "BLOCKED"


# Maps Phase 19 outcomes to existing execution statuses (base.py)
OUTCOME_TO_EXECUTION_STATUS = {
    SubmissionOutcome.SUBMIT_ATTEMPTED: "EXECUTING",
    SubmissionOutcome.SUBMITTED: "SUBMITTED",
    SubmissionOutcome.SUBMISSION_CONFIRMED: "SUBMISSION_CONFIRMED",
    SubmissionOutcome.SUBMISSION_UNCERTAIN: "SUBMISSION_UNKNOWN",
    SubmissionOutcome.SUBMISSION_FAILED: "EXECUTION_FAILED",
    SubmissionOutcome.DUPLICATE_SUSPECTED: "BLOCKED",
    SubmissionOutcome.BLOCKED: "BLOCKED",
}

# Maps Phase 19 outcomes to existing tracking statuses (application_tracking.py)
OUTCOME_TO_TRACKING_STATUS = {
    SubmissionOutcome.SUBMIT_ATTEMPTED: "EXECUTING",
    SubmissionOutcome.SUBMITTED: "SUBMITTED",
    SubmissionOutcome.SUBMISSION_CONFIRMED: "SUBMISSION_CONFIRMED",
    SubmissionOutcome.SUBMISSION_UNCERTAIN: "SUBMITTED",
    SubmissionOutcome.SUBMISSION_FAILED: "EXECUTING",
    SubmissionOutcome.DUPLICATE_SUSPECTED: "EXECUTING",
    SubmissionOutcome.BLOCKED: "EXECUTING",
}


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

class FailureType(str, Enum):
    """Specific failure reasons — never collapse into generic FAILED."""

    SUBMISSION_REJECTED = "SUBMISSION_REJECTED"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    AUTH_FAILURE = "AUTH_FAILURE"
    CAPTCHA_BLOCKED = "CAPTCHA_BLOCKED"
    NAVIGATION_FAILURE = "NAVIGATION_FAILURE"
    CONFIRMATION_MISSING = "CONFIRMATION_MISSING"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    NETWORK_ERROR = "NETWORK_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"


# ---------------------------------------------------------------------------
# Duplicate detection result
# ---------------------------------------------------------------------------

class DuplicateVerdict(str, Enum):
    """Pre-submission duplicate check result."""

    SAFE_TO_SUBMIT = "SAFE_TO_SUBMIT"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    UNKNOWN = "UNKNOWN"


@dataclass
class DuplicateCheckResult:
    """Result of a pre-submission duplicate check."""

    verdict: DuplicateVerdict
    reason: str = ""
    existing_application_id: int | None = None
    existing_execution_id: int | None = None


# ---------------------------------------------------------------------------
# Confirmation detection
# ---------------------------------------------------------------------------

# Strong confirmation markers — explicit success language
_STRONG_CONFIRMATION_MARKERS = (
    "thank you for your application",
    "application submitted successfully",
    "application has been submitted",
    "your application has been received",
    "we have received your application",
    "successfully applied",
    "application received",
    "submission confirmed",
    "congratulations",
    "application complete",
    "your application is complete",
)

# Weak signals — insufficient alone for SUBMISSION_CONFIRMED
_WEAK_SIGNALS = (
    "processing",
    "please wait",
    "we are reviewing",
)

# Reference ID patterns: (label_regex, value_group)
_REFERENCE_PATTERNS = [
    # "Application ID: APP-12345" or "Application ID: 12345"
    (r"application\s+(?:id|number|#)\s*[:：]\s*(.+?)(?:\s|$|\.|,)", 1),
    # "Confirmation Number: 893241"
    (r"confirmation\s+(?:number|#|id)\s*[:：]\s*(.+?)(?:\s|$|\.|,)", 1),
    # "Reference ID: ABC123"
    (r"reference\s+(?:id|#|number)\s*[:：]\s*(.+?)(?:\s|$|\.|,)", 1),
    # "Candidate ID: C-456"
    (r"candidate\s+(?:id|#)\s*[:：]\s*(.+?)(?:\s|$|\.|,)", 1),
    # "Submission ID: S-789"
    (r"submission\s+(?:id|#)\s*[:：]\s*(.+?)(?:\s|$|\.|,)", 1),
    # "Your application number is 12345"
    (r"(?:your\s+)?application\s+(?:number|id)\s+is\s+(.+?)(?:\s|$|\.|,)", 1),
    # "Reference: REF-2026-55555"
    (r"reference\s*[:：]\s*(.+?)(?:\s|$|\.|,)", 1),
]


@dataclass
class ConfirmationEvidence:
    """Structured evidence for post-submission verification."""

    outcome: SubmissionOutcome
    confidence: str = "NONE"  # STRONG | WEAK | NONE
    confirmation_type: str = ""  # explicit_page | success_text | reference_id | url_change | none
    confirmation_text: str = ""
    confirmation_reference_id: str | None = None
    confirmation_url: str | None = None
    page_identifier: str = ""
    observed_at: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    failure_type: FailureType | None = None
    failure_message: str = ""

    def __post_init__(self):
        if not self.observed_at:
            self.observed_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Confirmation detection functions
# ---------------------------------------------------------------------------

def detect_confirmation(
    page_text: str,
    current_url: str,
    previous_url: str | None = None,
    *,
    has_reference_id: bool = False,
) -> ConfirmationEvidence:
    """Analyze page text and URL to determine submission outcome.

    Uses rule-based detection with strong/weak signal separation.
    Weak signals alone never produce SUBMISSION_CONFIRMED.
    """
    text_lower = page_text.lower().strip()
    observed_at = datetime.now(timezone.utc).isoformat()

    # 1. Check for strong confirmation text
    strong_match = any(marker in text_lower for marker in _STRONG_CONFIRMATION_MARKERS)

    # 2. Check for reference ID
    ref_id = extract_reference_id(page_text)

    # 3. Check for URL-based confirmation
    url_changed = previous_url is not None and current_url != previous_url
    url_has_confirm = "confirm" in current_url.lower() or "success" in current_url.lower()

    # 4. Check for explicit rejection
    rejection_markers = (
        "we regret to inform",
        "your application was not selected",
        "position has been filled",
        "position is no longer available",
        "application rejected",
        "not moving forward",
    )
    is_rejected = any(marker in text_lower for marker in rejection_markers)

    # 5. Check for duplicate warning
    duplicate_markers = (
        "you have already applied",
        "duplicate application",
        "already submitted an application",
        "you already have an application",
    )
    is_duplicate_warning = any(marker in text_lower for marker in duplicate_markers)

    # 6. Determine outcome
    if is_rejected:
        return ConfirmationEvidence(
            outcome=SubmissionOutcome.SUBMISSION_FAILED,
            confidence="STRONG",
            confirmation_type="rejection_text",
            confirmation_text=page_text[:2000],
            confirmation_url=current_url,
            observed_at=observed_at,
            failure_type=FailureType.SUBMISSION_REJECTED,
            failure_message="Site explicitly rejected the application.",
        )

    if is_duplicate_warning:
        return ConfirmationEvidence(
            outcome=SubmissionOutcome.DUPLICATE_SUSPECTED,
            confidence="STRONG",
            confirmation_type="duplicate_warning",
            confirmation_text=page_text[:2000],
            confirmation_url=current_url,
            observed_at=observed_at,
            failure_type=FailureType.DUPLICATE_SUSPECTED,
            failure_message="Site indicates a duplicate application already exists.",
        )

    # Strong confirmation: explicit success text + optionally reference ID
    if strong_match:
        return ConfirmationEvidence(
            outcome=SubmissionOutcome.SUBMISSION_CONFIRMED,
            confidence="STRONG",
            confirmation_type="success_text" if not ref_id else "reference_id",
            confirmation_text=_extract_success_snippet(page_text),
            confirmation_reference_id=ref_id,
            confirmation_url=current_url,
            observed_at=observed_at,
        )

    # Reference ID alone is strong evidence
    if ref_id:
        return ConfirmationEvidence(
            outcome=SubmissionOutcome.SUBMISSION_CONFIRMED,
            confidence="STRONG",
            confirmation_type="reference_id",
            confirmation_text=_extract_success_snippet(page_text),
            confirmation_reference_id=ref_id,
            confirmation_url=current_url,
            observed_at=observed_at,
        )

    # URL changed to confirmation page — weak signal
    if url_has_confirm and url_changed:
        return ConfirmationEvidence(
            outcome=SubmissionOutcome.SUBMITTED,
            confidence="WEAK",
            confirmation_type="url_change",
            confirmation_text=page_text[:1000],
            confirmation_url=current_url,
            observed_at=observed_at,
        )

    # Only weak signals present
    weak_match = any(signal in text_lower for signal in _WEAK_SIGNALS)
    if weak_match and url_changed:
        return ConfirmationEvidence(
            outcome=SubmissionOutcome.SUBMITTED,
            confidence="WEAK",
            confirmation_type="weak_navigation",
            confirmation_text=page_text[:1000],
            confirmation_url=current_url,
            observed_at=observed_at,
        )

    # No confirmation evidence at all
    return ConfirmationEvidence(
        outcome=SubmissionOutcome.SUBMISSION_UNCERTAIN,
        confidence="NONE",
        confirmation_type="none",
        confirmation_text=page_text[:2000],
        confirmation_url=current_url,
        observed_at=observed_at,
        failure_type=FailureType.CONFIRMATION_MISSING,
        failure_message="No confirmation evidence found after submission.",
    )


def extract_reference_id(page_text: str) -> str | None:
    """Extract application/reference ID from page text.

    Only extracts when a clear label context exists.
    Never invents or guesses IDs.
    """
    for pattern, group in _REFERENCE_PATTERNS:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            value = match.group(group).strip()
            # Validate: must be non-empty, not just whitespace/punctuation
            value = value.rstrip(".:,; ")
            if value and len(value) >= 2:
                return value
    return None


def _extract_success_snippet(page_text: str) -> str:
    """Extract a short snippet around the first success marker."""
    text_lower = page_text.lower()
    for marker in _STRONG_CONFIRMATION_MARKERS:
        idx = text_lower.find(marker)
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(page_text), idx + len(marker) + 100)
            return page_text[start:end].strip()
    return page_text[:500]


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def check_duplicate(
    job_id: int | None = None,
    job_url: str | None = None,
    company: str | None = None,
    existing_applications: list[dict] | None = None,
    existing_executions: list[dict] | None = None,
) -> DuplicateCheckResult:
    """Check whether this job has already been applied to.

    Compares job_id, job_url, and existing application/execution records.
    Never destroys or overwrites prior history.
    """
    existing_applications = existing_applications or []
    existing_executions = existing_executions or []

    # Check existing applications by job_id
    if job_id is not None:
        for app in existing_applications:
            if app.get("job_id") == job_id:
                status = app.get("lifecycle_status", "")
                if status in ("SUBMISSION_CONFIRMED", "SUBMITTED"):
                    return DuplicateCheckResult(
                        verdict=DuplicateVerdict.ALREADY_APPLIED,
                        reason=(
                            f"Application #{app.get('id')} already exists "
                            f"with status '{status}'."
                        ),
                        existing_application_id=app.get("id"),
                    )
                if status in ("EXECUTING", "EXECUTION_READY", "AWAITING_APPROVAL"):
                    return DuplicateCheckResult(
                        verdict=DuplicateVerdict.DUPLICATE_SUSPECTED,
                        reason=(
                            f"Application #{app.get('id')} is in progress "
                            f"with status '{status}'."
                        ),
                        existing_application_id=app.get("id"),
                    )

    # Check existing executions by package (external action statuses)
    for exc in existing_executions:
        exc_status = exc.get("status", "")
        if exc_status in ("SUBMITTED", "SUBMISSION_CONFIRMED"):
            return DuplicateCheckResult(
                verdict=DuplicateVerdict.ALREADY_APPLIED,
                reason=(
                    f"Execution #{exc.get('id')} already ended in "
                    f"'{exc_status}'."
                ),
                existing_execution_id=exc.get("id"),
            )
        if exc_status == "SUBMISSION_UNKNOWN":
            return DuplicateCheckResult(
                verdict=DuplicateVerdict.DUPLICATE_SUSPECTED,
                reason=(
                    f"Prior execution #{exc.get('id')} ended as uncertain. "
                    "Human review required before retry."
                ),
                existing_execution_id=exc.get("id"),
            )

    return DuplicateCheckResult(verdict=DuplicateVerdict.SAFE_TO_SUBMIT)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

# Safe to retry automatically (pre-submit only)
_RETRYABLE_ERRORS = {
    FailureType.NAVIGATION_FAILURE,
    FailureType.BROWSER_ERROR,
    FailureType.NETWORK_ERROR,
}

# Never retry automatically
_NON_RETRYABLE_ERRORS = {
    FailureType.CAPTCHA_BLOCKED,
    FailureType.AUTH_FAILURE,
    FailureType.SUBMISSION_REJECTED,
    FailureType.DUPLICATE_SUSPECTED,
    FailureType.CONFIRMATION_MISSING,
    FailureType.VALIDATION_FAILURE,
}


def is_retryable(failure_type: FailureType, *, after_submit: bool = False) -> bool:
    """Determine if a failure is safe to retry.

    After submit, never retry automatically — uncertain outcomes require
    human review to prevent duplicate applications.
    """
    if after_submit:
        return False
    return failure_type in _RETRYABLE_ERRORS


def should_block_retry(outcome: SubmissionOutcome) -> bool:
    """Determine if future runs should be blocked pending review."""
    return outcome in (
        SubmissionOutcome.SUBMISSION_UNCERTAIN,
        SubmissionOutcome.DUPLICATE_SUSPECTED,
        SubmissionOutcome.BLOCKED,
    )
