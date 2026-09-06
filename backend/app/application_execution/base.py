"""Shared types, constants and errors for the execution engine.

Modes and statuses are stored as plain strings so they persist into the
database without an enum dance. The policy engine is the only place that maps
a platform to a mode; platform code never re-decides on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# ---------------------------------------------------------------------------
# Execution modes (policy output)
# ---------------------------------------------------------------------------
AUTHORIZED_AUTOMATION = "AUTHORIZED_AUTOMATION"
PERMITTED_BROWSER = "PERMITTED_BROWSER"
HUMAN_ASSISTED = "HUMAN_ASSISTED"
UNSUPPORTED = "UNSUPPORTED"
EXECUTION_MODES = (
    AUTHORIZED_AUTOMATION,
    PERMITTED_BROWSER,
    HUMAN_ASSISTED,
    UNSUPPORTED,
)

# ---------------------------------------------------------------------------
# Execution statuses
# ---------------------------------------------------------------------------
STATUS_EXECUTION_READY = "EXECUTION_READY"
STATUS_EXECUTING = "EXECUTING"
STATUS_AWAITING_APPROVAL = "AWAITING_APPROVAL"
STATUS_AWAITING_USER = "AWAITING_USER"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_SUBMISSION_CONFIRMED = "SUBMISSION_CONFIRMED"
STATUS_SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
STATUS_EXECUTION_FAILED = "EXECUTION_FAILED"
STATUS_BLOCKED = "BLOCKED"
STATUS_CANCELLED = "CANCELLED"

_TERMINAL_STATUSES = {
    STATUS_SUBMITTED,
    STATUS_SUBMISSION_CONFIRMED,
    STATUS_SUBMISSION_UNKNOWN,
    STATUS_EXECUTION_FAILED,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
}

_EXTERNAL_ACTION_STATUSES = {
    STATUS_SUBMITTED,
    STATUS_SUBMISSION_CONFIRMED,
    STATUS_SUBMISSION_UNKNOWN,
}

# ---------------------------------------------------------------------------
# Verification results (only require CONFIRMED for hard evidence)
# ---------------------------------------------------------------------------
VERIFICATION_CONFIRMED = "CONFIRMED"
VERIFICATION_LIKELY = "LIKELY"
VERIFICATION_UNKNOWN = "UNKNOWN"
VERIFICATION_FAILED = "FAILED"
VERIFICATION_RESULTS = (
    VERIFICATION_CONFIRMED,
    VERIFICATION_LIKELY,
    VERIFICATION_UNKNOWN,
    VERIFICATION_FAILED,
)

# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------
KNOWN = "KNOWN"
UNKNOWN = "UNKNOWN"
REQUIRES_REVIEW = "REQUIRES_REVIEW"

FIELD_KINDS = ("text", "textarea", "select", "radio", "checkbox", "file", "date")

LOGGED_IN_STATUSES = ("applied", "submitted", "interviewing", "offered", "rejected", "withdrawn")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExecutionError(Exception):
    """Base error for the execution engine."""


class ExecutionBlockedError(ExecutionError):
    """Execution cannot (or must not) continue; carries a target status."""

    def __init__(self, status: str, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.status = status
        self.reason = reason


class ExecutionNotFoundError(ExecutionError):
    """A requested execution (or package) does not exist."""


class ExecutionConflictError(ExecutionError):
    """An action is invalid for the current execution state."""


class ExecutionPolicyError(ExecutionError):
    """The resolved policy forbids the requested action."""


class BrowserUnavailableError(ExecutionError):
    """No usable browser driver is available."""


# ---------------------------------------------------------------------------
# Data records passed between layers
# ---------------------------------------------------------------------------


@dataclass
class DetectionResult:
    """What the detector concluded for a URL/source before any browser work."""

    platform: str  # linkedin | indeed | naukri | company_career | generic
    url: str | None
    hostname: str | None = None
    career_site: bool = False  # host is a known ATS / career portal
    based_on: str = "url"  # url | application_url | source
    confidence: str = "medium"  # high | medium | low

    @property
    def label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)


@dataclass
class PolicyDecision:
    """Verified execution policy for one platform + stored configuration."""

    platform: str
    mode: str = HUMAN_ASSISTED
    reason: str = "Default: human-assisted until verified."
    supports_browser_automation: bool = False
    supports_automated_submit: bool = False
    requires_user_approval: bool = True
    # Security-sensitive conditions we refuse to act on, e.g. CAPTCHA.
    hard_blockers: tuple[str, ...] = ("captcha", "anti_bot")

    def block(self, reason: str) -> bool:
        return any(blocker in reason.lower() for blocker in self.hard_blockers)


@dataclass
class DetectedField:
    """A raw form control discovered on the application page."""

    key: str = ""  # stable id (label normalized or element id)
    label: str = ""
    kind: str = "text"  # text | textarea | select | radio | checkbox | file | date
    required: bool = False
    options: list[str] = field(default_factory=list)  # normalized option labels
    # KNOWN | UNKNOWN | REQUIRES_REVIEW  (set by the mapper)
    classification: str = UNKNOWN
    value: str | None = None
    matched_key: str | None = None  # canonical field key e.g. "first_name"
    ambiguity: str | None = field(default=None)  # why we stopped, if any


@dataclass
class FillResult:
    key: str = ""
    label: str = ""
    status: str = UNKNOWN  # KNOWN | REQUIRES_REVIEW | UNKNOWN
    value: str | None = None
    message: str = ""


@dataclass
class NewQuestion:
    """A free-text field that maps to no prepared answer."""

    label: str
    recommended_answer: str | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class SubmissionResult:
    confirmed: bool = False
    failure: bool = False
    reference: str | None = None
    url: str | None = None
    message: str = ""
    raw_text: str = ""


@dataclass
class ApprovalPayload:
    """Everything the human needs before authorizing submission."""

    platform: str = ""
    company: str = ""
    job_title: str = ""
    job_url: str = ""
    resume_name: str = ""
    package_version: int = 0
    execution_mode: str = HUMAN_ASSISTED
    fields_detected: int = 0
    fields_completed: int = 0
    fields_needing_review: int = 0
    answered_questions: int = 0
    warnings: list[str] = field(default_factory=list)
    auto_submit_allowed: bool = False
    recommended_action: str = "submit"  # submit | complete_manually | cannot_submit


# ---------------------------------------------------------------------------
# Driver protocol
# ---------------------------------------------------------------------------


class BrowserDriver(Protocol):
    """Minimal safe browser surface. Real drivers NEVER expose arbitrary
    selectors/evasion; the executor only uses the operations below."""

    def open(self, url: str) -> dict: ...
    def inspect_form(self) -> list[DetectedField]: ...
    def fill(self, target_key: str, value: str) -> FillResult: ...
    def upload_resume(self, data: bytes, file_name: str, content_type: str) -> FillResult: ...
    def submit(self) -> SubmissionResult: ...
    def detect_captcha(self) -> bool: ...
    def detect_login(self) -> bool: ...
    def screenshot(self, label: str) -> str | None: ...
    def close(self) -> None: ...


PLATFORM_LABELS = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "naukri": "Naukri",
    "company_career": "Company career site",
    "generic": "Application page",
}
