"""Pre-execution job recheck and application preflight (Phase 20).

Every application is re-validated immediately before browser execution.
The agent never wastes execution on expired, closed, removed, or
duplicate listings, or on stale/incomplete packages.

Preflight flow:
    QUEUE → RECHECK JOB → RECHECK URL → RECHECK DEADLINE
    → RECHECK DUPLICATE → RECHECK PACKAGE → EXECUTION ELIGIBILITY
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

# ---------------------------------------------------------------------------
# Job availability classification
# ---------------------------------------------------------------------------

class JobAvailability(str, Enum):
    """Deterministic post-recheck listing status."""

    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    REMOVED = "REMOVED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Reason codes — machine-readable failure reasons
# ---------------------------------------------------------------------------

class ReasonCode(str, Enum):
    """Every failed preflight condition has a machine-readable code."""

    JOB_EXPIRED = "JOB_EXPIRED"
    JOB_CLOSED = "JOB_CLOSED"
    JOB_REMOVED = "JOB_REMOVED"
    JOB_UNAVAILABLE = "JOB_UNAVAILABLE"
    JOB_STATE_UNKNOWN = "JOB_STATE_UNKNOWN"
    JOB_MISMATCH = "JOB_MISMATCH"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    DEADLINE_PASSED = "DEADLINE_PASSED"
    DEADLINE_EXPIRING_SOON = "DEADLINE_EXPIRING_SOON"
    DUPLICATE_APPLICATION = "DUPLICATE_APPLICATION"
    DUPLICATE_SUSPECTED = "DUPLICATE_SUSPECTED"
    PACKAGE_MISSING = "PACKAGE_MISSING"
    PACKAGE_INVALID = "PACKAGE_INVALID"
    PACKAGE_NOT_APPROVED = "PACKAGE_NOT_APPROVED"
    RESUME_MISSING = "RESUME_MISSING"
    REQUIRED_DOCUMENT_MISSING = "REQUIRED_DOCUMENT_MISSING"
    PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"
    SENSITIVE_VALUE_UNKNOWN = "SENSITIVE_VALUE_UNKNOWN"
    APPLICATION_URL_MISSING = "APPLICATION_URL_MISSING"
    PLATFORM_UNSUPPORTED = "PLATFORM_UNSUPPORTED"
    COMPANY_MISMATCH = "COMPANY_MISMATCH"
    TITLE_MISMATCH = "TITLE_MISMATCH"
    URL_MISMATCH = "URL_MISMATCH"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# Preflight result
# ---------------------------------------------------------------------------

@dataclass
class PreflightResult:
    """Structured, deterministic result of all pre-execution checks."""

    eligible: bool = False
    job_availability: JobAvailability = JobAvailability.UNKNOWN
    job_identity_valid: bool = True
    deadline_valid: bool = True
    duplicate_status: str = "SAFE_TO_SUBMIT"
    package_valid: bool = True
    profile_valid: bool = True
    authentication_ready: bool = True
    reason_codes: list[str] = field(default_factory=list)
    checked_at: str = ""
    job_id: int | None = None
    package_id: int | None = None

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()

    @property
    def blocked(self) -> bool:
        return not self.eligible

    @property
    def has_blockers(self) -> bool:
        _blockers = {
            ReasonCode.JOB_EXPIRED.value,
            ReasonCode.JOB_CLOSED.value,
            ReasonCode.JOB_REMOVED.value,
            ReasonCode.JOB_UNAVAILABLE.value,
            ReasonCode.JOB_MISMATCH.value,
            ReasonCode.COMPANY_MISMATCH.value,
            ReasonCode.TITLE_MISMATCH.value,
            ReasonCode.DUPLICATE_APPLICATION.value,
            ReasonCode.PACKAGE_MISSING.value,
            ReasonCode.PACKAGE_INVALID.value,
            ReasonCode.PACKAGE_NOT_APPROVED.value,
            ReasonCode.RESUME_MISSING.value,
            ReasonCode.APPLICATION_URL_MISSING.value,
            ReasonCode.CAPTCHA_DETECTED.value,
            ReasonCode.AUTH_REQUIRED.value,
            ReasonCode.DEADLINE_PASSED.value,
            ReasonCode.URL_MISMATCH.value,
        }
        return bool(_blockers & set(self.reason_codes))

    @property
    def needs_review(self) -> bool:
        _review = {
            ReasonCode.JOB_STATE_UNKNOWN.value,
            ReasonCode.DUPLICATE_SUSPECTED.value,
            ReasonCode.PROFILE_INCOMPLETE.value,
            ReasonCode.SENSITIVE_VALUE_UNKNOWN.value,
            ReasonCode.DEADLINE_EXPIRING_SOON.value,
        }
        return bool(_review & set(self.reason_codes))


# ---------------------------------------------------------------------------
# Deadline handling
# ---------------------------------------------------------------------------

# Default threshold: jobs expiring within this many days are flagged
DEFAULT_EXPIRING_SOON_DAYS = 3


def check_deadline(
    deadline: date | datetime | None,
    *,
    now: datetime | None = None,
    expiring_soon_days: int = DEFAULT_EXPIRING_SOON_DAYS,
) -> tuple[bool, str | None]:
    """Check whether an application deadline is still valid.

    Returns (valid, reason_code_or_none).
    """
    if deadline is None:
        return True, None

    clock = now or datetime.now(timezone.utc)
    today = clock.date()

    # Handle datetime vs date
    if isinstance(deadline, datetime):
        deadline_date = deadline.date()
    else:
        deadline_date = deadline

    if deadline_date < today:
        return False, ReasonCode.DEADLINE_PASSED.value

    days_remaining = (deadline_date - today).days
    if 0 < days_remaining <= expiring_soon_days:
        return True, ReasonCode.DEADLINE_EXPIRING_SOON.value

    return True, None


# ---------------------------------------------------------------------------
# Job availability detection
# ---------------------------------------------------------------------------

# Closure signals — strong text markers on a listing page
_CLOSED_MARKERS = (
    "this job has been closed",
    "this position has been filled",
    "no longer accepting applications",
    "this listing is no longer available",
    "job is no longer available",
    "position has been filled",
    "this job posting has expired",
    "this job has expired",
    "applications are closed",
    "this position is closed",
    "we are no longer accepting applications",
    "this posting has been removed",
    "job has been removed",
    "listing removed",
    "position no longer available",
)

_REMOVED_MARKERS = (
    "this job has been removed",
    "this listing has been removed",
    "job posting not found",
    "page not found",
    "404",
    "this posting does not exist",
)


def detect_listing_availability(
    page_text: str,
    http_status: int | None = None,
) -> JobAvailability:
    """Classify listing availability from page content and HTTP status.

    Uses multiple signals — never relies on HTTP 200 alone.
    """
    text_lower = (page_text or "").lower()

    # HTTP-level signals
    if http_status is not None:
        if http_status == 404:
            return JobAvailability.REMOVED
        if http_status == 410:
            return JobAvailability.REMOVED
        if http_status >= 500:
            return JobAvailability.UNKNOWN
        if http_status == 403:
            return JobAvailability.UNAVAILABLE

    # Explicit removed markers
    if any(marker in text_lower for marker in _REMOVED_MARKERS):
        return JobAvailability.REMOVED

    # Explicit closure markers
    if any(marker in text_lower for marker in _CLOSED_MARKERS):
        return JobAvailability.CLOSED

    # Application button disabled
    if "disabled" in text_lower and ("apply" in text_lower or "submit" in text_lower):
        # Check for explicit disabled apply button
        if any(phrase in text_lower for phrase in (
            "apply now", "submit application", "apply for this"
        )):
            return JobAvailability.CLOSED

    return JobAvailability.ACTIVE


def availability_from_freshness(freshness_status: str) -> JobAvailability:
    """Map existing freshness classification to availability.

    This is advisory — preflight recheck overrides discovery-time freshness.
    """
    mapping = {
        "VERY_FRESH": JobAvailability.ACTIVE,
        "FRESH": JobAvailability.ACTIVE,
        "RECENT": JobAvailability.ACTIVE,
        "AGING": JobAvailability.EXPIRING_SOON,
        "STALE": JobAvailability.EXPIRED,
        "UNKNOWN": JobAvailability.UNKNOWN,
    }
    return mapping.get(freshness_status, JobAvailability.UNKNOWN)


# ---------------------------------------------------------------------------
# Job identity validation
# ---------------------------------------------------------------------------

def _normalize_for_comparison(value: str | None) -> str:
    """Normalize a string for safe identity comparison."""
    if not value:
        return ""
    return " ".join(value.lower().strip().split())


def validate_job_identity(
    *,
    original_company: str | None = None,
    original_title: str | None = None,
    original_url: str | None = None,
    current_company: str | None = None,
    current_title: str | None = None,
    current_url: str | None = None,
) -> tuple[bool, list[str]]:
    """Compare discovered job metadata with the current listing.

    Returns (valid, list_of_mismatch_codes).
    """
    mismatches: list[str] = []

    # Company comparison
    if original_company and current_company:
        orig = _normalize_for_comparison(original_company)
        curr = _normalize_for_comparison(current_company)
        if orig and curr and orig != curr:
            mismatches.append(ReasonCode.COMPANY_MISMATCH.value)

    # Title comparison
    if original_title and current_title:
        orig = _normalize_for_comparison(original_title)
        curr = _normalize_for_comparison(current_title)
        if orig and curr and orig != curr:
            mismatches.append(ReasonCode.TITLE_MISMATCH.value)

    # URL comparison (exact match after normalization)
    if original_url and current_url:
        orig = original_url.strip().rstrip("/").lower()
        curr = current_url.strip().rstrip("/").lower()
        if orig and curr and orig != curr:
            # URL changes are suspicious but not always fatal —
            # flag for review if company/title also changed
            if mismatches:
                mismatches.append(ReasonCode.URL_MISMATCH.value)

    return len(mismatches) == 0, mismatches


# ---------------------------------------------------------------------------
# Package validation
# ---------------------------------------------------------------------------

def validate_package(
    package_status: str | None = None,
    quality_gate: str | None = None,
    selected_resume_id: int | None = None,
    resume_exists: bool = True,
    readiness: str | None = None,
) -> tuple[bool, list[str]]:
    """Validate that an application package is ready for execution.

    Returns (valid, list_of_reason_codes).
    """
    issues: list[str] = []

    if package_status is None:
        issues.append(ReasonCode.PACKAGE_MISSING.value)
        return False, issues

    if package_status != "APPROVED":
        issues.append(ReasonCode.PACKAGE_NOT_APPROVED.value)

    if quality_gate == "FAIL":
        issues.append(ReasonCode.PACKAGE_INVALID.value)

    if selected_resume_id is None:
        issues.append(ReasonCode.RESUME_MISSING.value)
    elif not resume_exists:
        issues.append(ReasonCode.RESUME_MISSING.value)

    if readiness == "NOT_READY":
        issues.append(ReasonCode.PACKAGE_INVALID.value)

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------

# Fields that are required for a valid application
_REQUIRED_PROFILE_FIELDS = ("name", "email")


def validate_profile(
    profile_data: dict | None = None,
    required_fields: tuple[str, ...] = _REQUIRED_PROFILE_FIELDS,
) -> tuple[bool, list[str]]:
    """Validate that required profile information is available.

    Returns (valid, list_of_reason_codes).
    """
    if profile_data is None:
        return False, [ReasonCode.PROFILE_INCOMPLETE.value]

    issues: list[str] = []
    for field_name in required_fields:
        value = profile_data.get(field_name)
        if not value or (isinstance(value, str) and not value.strip()):
            issues.append(ReasonCode.PROFILE_INCOMPLETE.value)
            break  # One code is enough

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Composite preflight check
# ---------------------------------------------------------------------------

def run_preflight_checks(
    *,
    job_id: int | None = None,
    job_availability: JobAvailability = JobAvailability.UNKNOWN,
    job_company: str | None = None,
    job_title: str | None = None,
    job_url: str | None = None,
    original_company: str | None = None,
    original_title: str | None = None,
    original_url: str | None = None,
    application_deadline: date | datetime | None = None,
    deadline_days: int = DEFAULT_EXPIRING_SOON_DAYS,
    package_id: int | None = None,
    package_status: str | None = None,
    quality_gate: str | None = None,
    selected_resume_id: int | None = None,
    resume_exists: bool = True,
    readiness: str | None = None,
    duplicate_status: str = "SAFE_TO_SUBMIT",
    profile_data: dict | None = None,
    application_url: str | None = None,
    captcha_detected: bool = False,
    auth_required: bool = False,
    now: datetime | None = None,
) -> PreflightResult:
    """Run all preflight checks and produce a structured result.

    This is the main entry point for pre-execution validation.
    Every check is deterministic — no LLM, no guessing.
    """
    reason_codes: list[str] = []

    # 1. Job availability
    if job_availability == JobAvailability.EXPIRED:
        reason_codes.append(ReasonCode.JOB_EXPIRED.value)
    elif job_availability == JobAvailability.CLOSED:
        reason_codes.append(ReasonCode.JOB_CLOSED.value)
    elif job_availability == JobAvailability.REMOVED:
        reason_codes.append(ReasonCode.JOB_REMOVED.value)
    elif job_availability == JobAvailability.UNAVAILABLE:
        reason_codes.append(ReasonCode.JOB_UNAVAILABLE.value)
    elif job_availability == JobAvailability.UNKNOWN:
        reason_codes.append(ReasonCode.JOB_STATE_UNKNOWN.value)

    # 2. Job identity
    if original_company or original_title:
        identity_valid, identity_mismatches = validate_job_identity(
            original_company=original_company,
            original_title=original_title,
            original_url=original_url,
            current_company=job_company,
            current_title=job_title,
            current_url=job_url,
        )
        if not identity_valid:
            reason_codes.extend(identity_mismatches)

    # 3. Deadline
    deadline_valid, deadline_code = check_deadline(
        application_deadline, now=now, expiring_soon_days=deadline_days,
    )
    if deadline_code:
        reason_codes.append(deadline_code)

    # 4. Duplicate
    if duplicate_status == "ALREADY_APPLIED":
        reason_codes.append(ReasonCode.DUPLICATE_APPLICATION.value)
    elif duplicate_status == "DUPLICATE_SUSPECTED":
        reason_codes.append(ReasonCode.DUPLICATE_SUSPECTED.value)

    # 5. Package
    pkg_valid, pkg_issues = validate_package(
        package_status=package_status,
        quality_gate=quality_gate,
        selected_resume_id=selected_resume_id,
        resume_exists=resume_exists,
        readiness=readiness,
    )
    reason_codes.extend(pkg_issues)

    # 6. Profile
    prof_valid, prof_issues = validate_profile(profile_data)
    reason_codes.extend(prof_issues)

    # 7. Application URL
    if not application_url:
        reason_codes.append(ReasonCode.APPLICATION_URL_MISSING.value)

    # 8. CAPTCHA / Auth
    if captcha_detected:
        reason_codes.append(ReasonCode.CAPTCHA_DETECTED.value)
    if auth_required:
        reason_codes.append(ReasonCode.AUTH_REQUIRED.value)

    # 9. Determine eligibility
    _blocker_codes = {
        ReasonCode.JOB_EXPIRED.value,
        ReasonCode.JOB_CLOSED.value,
        ReasonCode.JOB_REMOVED.value,
        ReasonCode.JOB_UNAVAILABLE.value,
        ReasonCode.JOB_MISMATCH.value,
        ReasonCode.COMPANY_MISMATCH.value,
        ReasonCode.TITLE_MISMATCH.value,
        ReasonCode.DUPLICATE_APPLICATION.value,
        ReasonCode.PACKAGE_MISSING.value,
        ReasonCode.PACKAGE_INVALID.value,
        ReasonCode.PACKAGE_NOT_APPROVED.value,
        ReasonCode.RESUME_MISSING.value,
        ReasonCode.APPLICATION_URL_MISSING.value,
        ReasonCode.CAPTCHA_DETECTED.value,
        ReasonCode.AUTH_REQUIRED.value,
        ReasonCode.DEADLINE_PASSED.value,
        ReasonCode.URL_MISMATCH.value,
    }
    _review_codes = {
        ReasonCode.JOB_STATE_UNKNOWN.value,
        ReasonCode.DEADLINE_EXPIRING_SOON.value,
        ReasonCode.DUPLICATE_SUSPECTED.value,
        ReasonCode.PROFILE_INCOMPLETE.value,
        ReasonCode.JOB_NOT_FOUND.value,
    }
    has_blockers = bool(_blocker_codes & set(reason_codes))
    bool(_review_codes & set(reason_codes))

    # Eligible only if ACTIVE or EXPIRING_SOON and no blockers
    eligible = (
        job_availability in (JobAvailability.ACTIVE, JobAvailability.EXPIRING_SOON)
        and not has_blockers
    )
    # Profile incomplete prevents auto-eligibility
    if ReasonCode.PROFILE_INCOMPLETE.value in reason_codes:
        eligible = False

    return PreflightResult(
        eligible=eligible,
        job_availability=job_availability,
        job_identity_valid=ReasonCode.JOB_MISMATCH.value not in reason_codes
            and ReasonCode.COMPANY_MISMATCH.value not in reason_codes
            and ReasonCode.TITLE_MISMATCH.value not in reason_codes,
        deadline_valid=deadline_valid,
        duplicate_status=duplicate_status,
        package_valid=pkg_valid,
        profile_valid=prof_valid,
        authentication_ready=not captcha_detected and not auth_required,
        reason_codes=reason_codes,
        job_id=job_id,
        package_id=package_id,
    )
