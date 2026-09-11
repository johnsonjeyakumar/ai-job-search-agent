"""Application readiness gate (Phase 22).

Deterministic pre-execution validation that answers:
    "Do we have everything required to safely and truthfully apply
     for this specific job?"

Readiness flow:
    JOB QUALIFIES → PROFILE CHECK → REQUIRED ANSWERS CHECK
    → REQUIRED DOCUMENT CHECK → APPLICATION PACKAGE CHECK
    → PREFLIGHT CHECK → DUPLICATE CHECK → AUTH READINESS
    → READINESS DECISION → AUTOPILOT / REVIEW / BLOCK

Safety rules:
    - Never fabricate applicant information.
    - Never infer sensitive information.
    - Never create fake answers to make an application READY.
    - Human review for ambiguous, sensitive, or unknown requirements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Readiness status
# ---------------------------------------------------------------------------

class ReadinessStatus(str, Enum):
    """Deterministic readiness classification."""

    READY = "READY"
    NEEDS_INPUT = "NEEDS_INPUT"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"


# ---------------------------------------------------------------------------
# Requirement categories
# ---------------------------------------------------------------------------

class RequirementCategory(str, Enum):
    """Canonical requirement categories for application readiness."""

    IDENTITY = "IDENTITY"
    CONTACT = "CONTACT"
    LOCATION = "LOCATION"
    EDUCATION = "EDUCATION"
    EXPERIENCE = "EXPERIENCE"
    SKILLS = "SKILLS"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    SPONSORSHIP = "SPONSORSHIP"
    AVAILABILITY = "AVAILABILITY"
    COMPENSATION = "COMPENSATION"
    RELOCATION = "RELOCATION"
    DOCUMENT = "DOCUMENT"
    PORTFOLIO = "PORTFOLIO"
    LINK = "LINK"
    DECLARATION = "DECLARATION"
    SIGNATURE = "SIGNATURE"
    CONSENT = "CONSENT"
    SENSITIVE = "SENSITIVE"
    CUSTOM = "CUSTOM"


# ---------------------------------------------------------------------------
# Requirement status
# ---------------------------------------------------------------------------

class RequirementStatus(str, Enum):
    """Status of an individual requirement check."""

    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTORY = "CONTRADICTORY"
    UNSAFE = "UNSAFE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"
    UNVERIFIED = "UNVERIFIED"


# ---------------------------------------------------------------------------
# Requirement source
# ---------------------------------------------------------------------------

class RequirementSource(str, Enum):
    """Where the requirement value comes from."""

    PROFILE = "profile"
    APPLICATION_ANSWER = "application_answer"
    APPLICATION_MEMORY = "application_memory"
    VERIFIED_RESUME = "verified_resume"
    VERIFIED_PACKAGE = "verified_package"
    FORM_DERIVED = "form_derived"
    EXPLICIT_USER = "explicit_user"
    JOB_SPECIFIC = "job_specific"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Requirement dataclass
# ---------------------------------------------------------------------------

@dataclass
class Requirement:
    """A single requirement for application readiness."""

    category: str
    label: str
    source: str = RequirementSource.UNKNOWN
    status: str = RequirementStatus.MISSING
    value: Any = None
    reason: str = ""
    is_sensitive: bool = False
    is_document: bool = False
    document_type: str | None = None
    field_key: str | None = None
    required: bool = False


# ---------------------------------------------------------------------------
# Completeness result
# ---------------------------------------------------------------------------

@dataclass
class CompletenessResult:
    """Profile completeness evaluation."""

    total_fields: int = 0
    filled_fields: int = 0
    score: float = 0.0
    field_status: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        if self.total_fields > 0:
            self.score = round(self.filled_fields / self.total_fields * 100, 1)


# ---------------------------------------------------------------------------
# Readiness result
# ---------------------------------------------------------------------------

@dataclass
class ReadinessResult:
    """Structured result of all readiness checks."""

    status: str = ReadinessStatus.INCOMPLETE
    completeness: CompletenessResult | None = None
    required_count: int = 0
    satisfied_count: int = 0
    missing_requirements: list[Requirement] = field(default_factory=list)
    invalid_requirements: list[Requirement] = field(default_factory=list)
    ambiguous_requirements: list[Requirement] = field(default_factory=list)
    contradictory_requirements: list[Requirement] = field(default_factory=list)
    sensitive_requirements: list[Requirement] = field(default_factory=list)
    all_requirements: list[Requirement] = field(default_factory=list)
    document_status: dict[str, str] = field(default_factory=dict)
    package_status: str = ""
    preflight_status: str = ""
    duplicate_status: str = ""
    previous_execution_blockers: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    checked_at: str = ""
    application_id: int | None = None
    job_id: int | None = None
    package_id: int | None = None

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_ready(self) -> bool:
        return self.status == ReadinessStatus.READY

    @property
    def has_blockers(self) -> bool:
        return self.status in (
            ReadinessStatus.BLOCKED,
            ReadinessStatus.INVALID,
        )

    @property
    def needs_attention(self) -> bool:
        return self.status in (
            ReadinessStatus.NEEDS_INPUT,
            ReadinessStatus.REVIEW,
        )


# ---------------------------------------------------------------------------
# Profile field definitions for completeness check
# ---------------------------------------------------------------------------

_PROFILE_FIELDS = {
    "name": {"label": "Name", "required": True, "category": "IDENTITY"},
    "email": {"label": "Email", "required": True, "category": "CONTACT"},
    "phone": {"label": "Phone", "required": True, "category": "CONTACT"},
    "city": {"label": "City", "required": False, "category": "LOCATION"},
    "state": {"label": "State", "required": False, "category": "LOCATION"},
    "country": {"label": "Country", "required": False, "category": "LOCATION"},
    "degree": {"label": "Degree", "required": False, "category": "EDUCATION"},
    "university": {"label": "University", "required": False, "category": "EDUCATION"},
    "graduation_year": {"label": "Graduation Year", "required": False, "category": "EDUCATION"},
    "experience_level": {"label": "Experience Level", "required": False, "category": "EXPERIENCE"},
    "skills": {"label": "Skills", "required": False, "category": "SKILLS"},
    "work_authorization": {
        "label": "Work Authorization", "required": False,
        "category": "WORK_AUTHORIZATION",
    },
    "salary_preference": {
        "label": "Salary Preference", "required": False,
        "category": "COMPENSATION",
    },
    "linkedin_url": {"label": "LinkedIn", "required": False, "category": "LINK"},
    "github_url": {"label": "GitHub", "required": False, "category": "LINK"},
    "portfolio_url": {"label": "Portfolio", "required": False, "category": "PORTFOLIO"},
}

# Sensitive fields — never inferred, always require explicit values
_SENSITIVE_FIELDS = frozenset({
    "work_authorization",
    "salary_preference",
    "gender",
    "relocation",
})

# Fields that should never be auto-filled from inference
_NEVER_INFERRABLE = frozenset({
    "gender",
    "relocation",
    "work_authorization",
    "sponsorship",
})


# ---------------------------------------------------------------------------
# Completeness evaluation
# ---------------------------------------------------------------------------

def evaluate_profile_completeness(profile_data: dict | None) -> CompletenessResult:
    """Evaluate how complete a profile is.

    This is informational only — completeness does NOT determine readiness.
    A 95% complete profile can still be BLOCKED if a single required value
    is missing.
    """
    if profile_data is None:
        return CompletenessResult(
            total_fields=len(_PROFILE_FIELDS),
            filled_fields=0,
            field_status={k: False for k in _PROFILE_FIELDS},
        )

    field_status = {}
    for field_name, spec in _PROFILE_FIELDS.items():
        value = profile_data.get(field_name)
        filled = _is_filled(value)
        field_status[field_name] = filled

    filled_count = sum(1 for v in field_status.values() if v)
    return CompletenessResult(
        total_fields=len(_PROFILE_FIELDS),
        filled_fields=filled_count,
        field_status=field_status,
    )


def _is_filled(value: Any) -> bool:
    """Check if a value is meaningfully filled."""
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, list) and len(value) == 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Application-specific requirement detection
# ---------------------------------------------------------------------------

# Default requirements that every application needs
_BASE_REQUIREMENTS: list[dict] = [
    {"category": "IDENTITY", "label": "Full Name", "field_key": "name",
     "required": True, "source": "profile"},
    {"category": "CONTACT", "label": "Email", "field_key": "email",
     "required": True, "source": "profile"},
    {"category": "CONTACT", "label": "Phone", "field_key": "phone",
     "required": True, "source": "profile"},
    {"category": "DOCUMENT", "label": "Resume", "field_key": "resume",
     "required": True, "source": "verified_package", "is_document": True,
     "document_type": "resume"},
]

# Conditional requirements — added based on form fields or job data
_CONDITIONAL_REQUIREMENTS: dict[str, dict] = {
    "WORK_AUTHORIZATION": {
        "category": "WORK_AUTHORIZATION",
        "label": "Work Authorization",
        "field_key": "work_authorization",
        "required": False,
        "source": "profile",
        "is_sensitive": True,
    },
    "SPONSORSHIP": {
        "category": "SPONSORSHIP",
        "label": "Visa Sponsorship",
        "field_key": "sponsorship",
        "required": False,
        "source": "profile",
        "is_sensitive": True,
    },
    "AVAILABILITY": {
        "category": "AVAILABILITY",
        "label": "Availability / Start Date",
        "field_key": "availability",
        "required": False,
        "source": "profile",
    },
    "COMPENSATION": {
        "category": "COMPENSATION",
        "label": "Expected Salary",
        "field_key": "salary_preference",
        "required": False,
        "source": "profile",
        "is_sensitive": True,
    },
    "RELOCATION": {
        "category": "RELOCATION",
        "label": "Willingness to Relocate",
        "field_key": "relocation",
        "required": False,
        "source": "profile",
        "is_sensitive": True,
    },
    "EDUCATION": {
        "category": "EDUCATION",
        "label": "Education",
        "field_key": "degree",
        "required": False,
        "source": "profile",
    },
    "EXPERIENCE": {
        "category": "EXPERIENCE",
        "label": "Years of Experience",
        "field_key": "experience_level",
        "required": False,
        "source": "profile",
    },
    "COVER_LETTER": {
        "category": "DOCUMENT",
        "label": "Cover Letter",
        "field_key": "cover_letter",
        "required": False,
        "source": "verified_package",
        "is_document": True,
        "document_type": "cover_letter",
    },
    "PORTFOLIO": {
        "category": "PORTFOLIO",
        "label": "Portfolio URL",
        "field_key": "portfolio_url",
        "required": False,
        "source": "profile",
    },
    "LINKEDIN": {
        "category": "LINK",
        "label": "LinkedIn Profile",
        "field_key": "linkedin_url",
        "required": False,
        "source": "profile",
    },
    "GITHUB": {
        "category": "LINK",
        "label": "GitHub Profile",
        "field_key": "github_url",
        "required": False,
        "source": "profile",
    },
}


def detect_requirements_from_form_fields(
    form_fields: list[dict] | None = None,
    job_data: dict | None = None,
) -> list[dict]:
    """Detect application-specific requirements from form fields and job data.

    Returns a list of requirement definitions that should be checked.
    """
    requirements = list(_BASE_REQUIREMENTS)
    detected_keys: set[str] = set()

    # Scan form fields for additional requirements
    if form_fields:
        for field_info in form_fields:
            label = (field_info.get("label") or "").lower()
            key = field_info.get("key", "")
            required = field_info.get("required", False)

            # Map form fields to requirement categories
            category = _map_form_field_to_category(label, key)
            if category and category in _CONDITIONAL_REQUIREMENTS:
                if category not in detected_keys:
                    req = dict(_CONDITIONAL_REQUIREMENTS[category])
                    if required:
                        req["required"] = True
                    requirements.append(req)
                    detected_keys.add(category)

    # Scan job data for additional requirements
    if job_data:
        job_desc = (job_data.get("description") or "").lower()
        job_data.get("tags") or []

        # Check if job mentions sponsorship
        if any(kw in job_desc for kw in ["sponsorship", "visa", "h1b", "h-1b"]):
            if "SPONSORSHIP" not in detected_keys:
                requirements.append(dict(_CONDITIONAL_REQUIREMENTS["SPONSORSHIP"]))
                detected_keys.add("SPONSORSHIP")

        # Check if job mentions relocation
        if any(kw in job_desc for kw in ["relocat", "on-site", "onsite"]):
            if "RELOCATION" not in detected_keys:
                requirements.append(dict(_CONDITIONAL_REQUIREMENTS["RELOCATION"]))
                detected_keys.add("RELOCATION")

        # Check if job mentions work authorization
        if any(kw in job_desc for kw in ["authorized to work", "work authorization",
                                          "right to work", "legally authorized"]):
            if "WORK_AUTHORIZATION" not in detected_keys:
                requirements.append(dict(_CONDITIONAL_REQUIREMENTS["WORK_AUTHORIZATION"]))
                detected_keys.add("WORK_AUTHORIZATION")

        # Check if job requires cover letter
        if any(kw in job_desc for kw in ["cover letter", "cover_letter"]):
            if "COVER_LETTER" not in detected_keys:
                requirements.append(dict(_CONDITIONAL_REQUIREMENTS["COVER_LETTER"]))
                detected_keys.add("COVER_LETTER")

        # Check if job mentions portfolio/github
        if any(kw in job_desc for kw in ["portfolio", "github", "personal website"]):
            if "PORTFOLIO" not in detected_keys:
                requirements.append(dict(_CONDITIONAL_REQUIREMENTS["PORTFOLIO"]))
                detected_keys.add("PORTFOLIO")

        # Check if job mentions linkedin
        if any(kw in job_desc for kw in ["linkedin"]):
            if "LINKEDIN" not in detected_keys:
                requirements.append(dict(_CONDITIONAL_REQUIREMENTS["LINKEDIN"]))
                detected_keys.add("LINKEDIN")

    return requirements


def _map_form_field_to_category(label: str, key: str) -> str | None:
    """Map a form field label/key to a requirement category."""
    combined = f"{label} {key}".lower()

    if any(kw in combined for kw in ["work auth", "visa status", "authorized to work",
                                      "right to work"]):
        return "WORK_AUTHORIZATION"
    if any(kw in combined for kw in ["sponsor", "visa sponsor", "h1b"]):
        return "SPONSORSHIP"
    if any(kw in combined for kw in ["availab", "start date", "join date"]):
        return "AVAILABILITY"
    if any(kw in combined for kw in ["salary", "compensation", "expected ctc", "pay"]):
        return "COMPENSATION"
    if any(kw in combined for kw in ["relocat", "willing to move"]):
        return "RELOCATION"
    if any(kw in combined for kw in ["cover letter", "coverletter", "motivation"]):
        return "COVER_LETTER"
    if any(kw in combined for kw in ["portfolio", "personal website", "personal site"]):
        return "PORTFOLIO"
    if any(kw in combined for kw in ["linkedin"]):
        return "LINKEDIN"
    if any(kw in combined for kw in ["github"]):
        return "GITHUB"
    if any(kw in combined for kw in ["degree", "qualification", "education", "university"]):
        return "EDUCATION"
    if any(kw in combined for kw in ["experience", "years"]):
        return "EXPERIENCE"
    return None


# ---------------------------------------------------------------------------
# Answer readiness
# ---------------------------------------------------------------------------

def check_answer_readiness(
    requirement: Requirement,
    profile_data: dict | None,
    answers: dict[str, str] | None = None,
    memory_answers: dict[str, str] | None = None,
) -> Requirement:
    """Check if a required answer is available and safe to use.

    Returns the requirement with status updated.
    """
    field_key = requirement.field_key
    if not field_key:
        return requirement

    # Check profile first
    if profile_data:
        value = profile_data.get(field_key)
        if _is_filled(value):
            # Sensitive fields need explicit verification
            if requirement.is_sensitive and field_key in _SENSITIVE_FIELDS:
                # Check if the value is a safe, explicit value
                if value and str(value).strip() and str(value).lower() not in (
                    "unknown", "n/a", "none", "unsure", "prefer not to say",
                ):
                    requirement.status = RequirementStatus.SATISFIED
                    requirement.value = value
                    requirement.source = RequirementSource.PROFILE
                    return requirement
                else:
                    requirement.status = RequirementStatus.UNSAFE
                    requirement.reason = (
                        f"Sensitive field '{requirement.label}' has ambiguous "
                        f"value '{value}'. Human review required."
                    )
                    return requirement
            else:
                requirement.status = RequirementStatus.SATISFIED
                requirement.value = value
                requirement.source = RequirementSource.PROFILE
                return requirement

    # Check application answers
    if answers:
        norm_key = field_key.lower().replace("_", " ").strip()
        for q, a in answers.items():
            q_norm = q.lower().replace("_", " ").strip()
            if norm_key in q_norm or q_norm in norm_key:
                if _is_filled(a):
                    requirement.status = RequirementStatus.SATISFIED
                    requirement.value = a
                    requirement.source = RequirementSource.APPLICATION_ANSWER
                    return requirement

    # Check memory answers
    if memory_answers:
        norm_key = field_key.lower().replace("_", " ").strip()
        for q, a in memory_answers.items():
            q_norm = q.lower().replace("_", " ").strip()
            if norm_key in q_norm or q_norm in norm_key:
                if _is_filled(a):
                    requirement.status = RequirementStatus.SATISFIED
                    requirement.value = a
                    requirement.source = RequirementSource.APPLICATION_MEMORY
                    return requirement

    # Not found — determine status based on requirement criticality
    if requirement.required:
        requirement.status = RequirementStatus.MISSING
        requirement.reason = f"Required field '{requirement.label}' is not available."
    else:
        requirement.status = RequirementStatus.NOT_APPLICABLE
        requirement.reason = f"Optional field '{requirement.label}' is not provided."

    return requirement


# ---------------------------------------------------------------------------
# Document readiness
# ---------------------------------------------------------------------------

def check_document_readiness(
    requirement: Requirement,
    package_data: dict | None,
    resume_data: dict | None = None,
) -> Requirement:
    """Check if a required document is available and valid.

    Returns the requirement with status updated.
    """
    if not requirement.is_document:
        return requirement

    doc_type = requirement.document_type

    if doc_type == "resume":
        return _check_resume_readiness(requirement, package_data, resume_data)
    elif doc_type == "cover_letter":
        return _check_cover_letter_readiness(requirement, package_data)
    else:
        return _check_generic_document_readiness(requirement, package_data)


def _check_resume_readiness(
    requirement: Requirement,
    package_data: dict | None,
    resume_data: dict | None,
) -> Requirement:
    """Check resume readiness."""
    if package_data is None:
        requirement.status = RequirementStatus.MISSING
        requirement.reason = "No application package found."
        return requirement

    selected_resume_id = package_data.get("selected_resume_id")
    if not selected_resume_id:
        requirement.status = RequirementStatus.MISSING
        requirement.reason = "No resume selected for this application."
        return requirement

    if resume_data is None:
        requirement.status = RequirementStatus.MISSING
        requirement.reason = "Selected resume not found."
        return requirement

    # Check resume validity
    file_path = resume_data.get("file_path")
    if not file_path:
        requirement.status = RequirementStatus.INVALID
        requirement.reason = "Resume has no associated file."
        return requirement

    is_active = resume_data.get("is_active", True)
    if not is_active:
        requirement.status = RequirementStatus.INVALID
        requirement.reason = "Selected resume is inactive."
        return requirement

    requirement.status = RequirementStatus.SATISFIED
    requirement.value = resume_data.get("name", "Resume")
    requirement.source = RequirementSource.VERIFIED_RESUME
    return requirement


def _check_cover_letter_readiness(
    requirement: Requirement,
    package_data: dict | None,
) -> Requirement:
    """Check cover letter readiness."""
    if package_data is None:
        if requirement.required:
            requirement.status = RequirementStatus.MISSING
            requirement.reason = "No application package found."
        else:
            requirement.status = RequirementStatus.NOT_APPLICABLE
        return requirement

    cover_letter = package_data.get("cover_letter")
    cover_letter_status = package_data.get("cover_letter_status", "skipped")

    if cover_letter and cover_letter_status in ("generated", "needs_review"):
        requirement.status = RequirementStatus.SATISFIED
        requirement.value = "Cover letter available"
        requirement.source = RequirementSource.VERIFIED_PACKAGE
        return requirement

    if requirement.required:
        requirement.status = RequirementStatus.MISSING
        requirement.reason = "Cover letter is required but not available."
    else:
        requirement.status = RequirementStatus.NOT_APPLICABLE
        requirement.reason = "Cover letter is optional and not provided."

    return requirement


def _check_generic_document_readiness(
    requirement: Requirement,
    package_data: dict | None,
) -> Requirement:
    """Check generic document readiness."""
    if requirement.required:
        requirement.status = RequirementStatus.MISSING
        requirement.reason = f"Required document '{requirement.label}' not found."
    else:
        requirement.status = RequirementStatus.NOT_APPLICABLE
    return requirement


# ---------------------------------------------------------------------------
# Profile vs application conflict detection
# ---------------------------------------------------------------------------

def detect_profile_conflicts(
    profile_data: dict | None,
    answers: dict[str, str] | None,
    memory_answers: dict[str, str] | None = None,
) -> list[Requirement]:
    """Detect contradictions between profile data and application answers.

    Returns list of contradictory requirements.
    """
    contradictions: list[Requirement] = []

    if not profile_data or not answers:
        return contradictions

    # Fields where we check for contradictions
    conflict_fields = {
        "city": ["city", "location", "current city"],
        "state": ["state", "province"],
        "country": ["country", "nation"],
        "experience_level": ["experience", "years of experience"],
        "degree": ["degree", "education", "qualification"],
    }

    for profile_field, answer_keywords in conflict_fields.items():
        profile_value = profile_data.get(profile_field)
        if not profile_value or not _is_filled(profile_value):
            continue

        for question, answer in answers.items():
            q_lower = question.lower()
            if any(kw in q_lower for kw in answer_keywords):
                ans_str = str(answer).strip().lower()
                prof_str = str(profile_value).strip().lower()
                if _is_filled(answer) and ans_str != prof_str:
                    contradictions.append(Requirement(
                        category="CUSTOM",
                        label=f"Conflicting {profile_field}",
                        status=RequirementStatus.CONTRADICTORY,
                        value={
                            "profile": profile_value,
                            "application": answer,
                        },
                        reason=(
                            f"Profile {profile_field}='{profile_value}' "
                            f"conflicts with application answer='{answer}'."
                        ),
                    ))

    return contradictions


# ---------------------------------------------------------------------------
# Previous execution blockers
# ---------------------------------------------------------------------------

def check_previous_execution_blockers(
    executions: list[dict] | None,
) -> list[str]:
    """Check if previous execution history blocks a new attempt.

    Returns list of blocker reasons.
    """
    blockers: list[str] = []

    if not executions:
        return blockers

    for exec_data in executions:
        status = exec_data.get("status", "")
        submission_status = exec_data.get("submission_status")

        if status == "SUBMISSION_UNKNOWN":
            blockers.append(
                f"Previous execution (id={exec_data.get('id')}) has uncertain "
                f"submission status. Human review required."
            )
        elif status == "BLOCKED":
            blockers.append(
                f"Previous execution (id={exec_data.get('id')}) was blocked."
            )
        elif submission_status == "UNKNOWN":
            blockers.append(
                f"Previous execution (id={exec_data.get('id')}) has unknown "
                f"submission outcome."
            )

    return blockers


# ---------------------------------------------------------------------------
# Package readiness
# ---------------------------------------------------------------------------

def check_package_readiness(
    package_data: dict | None,
) -> tuple[str, list[str]]:
    """Validate the complete application package.

    Returns (status, list_of_reasons).
    """
    if package_data is None:
        return ReadinessStatus.BLOCKED, ["No application package found."]

    reasons: list[str] = []
    status = package_data.get("status", "")
    quality_gate = package_data.get("quality_gate", "")
    readiness = package_data.get("readiness", "")

    if status != "APPROVED":
        reasons.append(f"Package status is '{status}', expected 'APPROVED'.")

    if quality_gate == "FAIL":
        reasons.append("Package quality gate failed.")

    if readiness == "NOT_READY":
        reasons.append("Package readiness is NOT_READY.")

    if not reasons:
        return ReadinessStatus.READY, []

    if quality_gate == "FAIL" or readiness == "NOT_READY":
        return ReadinessStatus.INVALID, reasons

    return ReadinessStatus.REVIEW, reasons


# ---------------------------------------------------------------------------
# Final readiness decision
# ---------------------------------------------------------------------------

def determine_readiness(
    requirements: list[Requirement],
    completeness: CompletenessResult,
    package_status: str,
    preflight_status: str,
    duplicate_status: str,
    previous_blockers: list[str],
) -> ReadinessResult:
    """Determine final readiness from all check results.

    This applies deterministic decision rules — no LLM override.
    """
    reason_codes: list[str] = []

    # Categorize requirements
    missing = [r for r in requirements if r.status == RequirementStatus.MISSING]
    invalid = [r for r in requirements if r.status == RequirementStatus.INVALID]
    ambiguous = [r for r in requirements if r.status == RequirementStatus.AMBIGUOUS]
    contradictory = [r for r in requirements if r.status == RequirementStatus.CONTRADICTORY]
    unsafe = [r for r in requirements if r.status == RequirementStatus.UNSAFE]
    sensitive = [r for r in requirements if r.is_sensitive]

    required_count = sum(1 for r in requirements if r.required)
    satisfied_count = sum(1 for r in requirements if r.status == RequirementStatus.SATISFIED)

    # Build reason codes
    if missing:
        reason_codes.append("REQUIRED_FIELDS_MISSING")
    if invalid:
        reason_codes.append("INVALID_REQUIREMENTS")
    if ambiguous:
        reason_codes.append("AMBIGUOUS_ANSWERS")
    if contradictory:
        reason_codes.append("CONTRADICTORY_DATA")
    if unsafe:
        reason_codes.append("SENSITIVE_VALUE_UNSAFE")
    if previous_blockers:
        reason_codes.append("PREVIOUS_EXECUTION_BLOCKER")

    # ── Decision rules ──────────────────────────────────────────────────

    # 1. Package invalid → BLOCKED
    if package_status == ReadinessStatus.INVALID:
        return ReadinessResult(
            status=ReadinessStatus.BLOCKED,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 2. Duplicate → BLOCKED
    if duplicate_status == "ALREADY_APPLIED":
        reason_codes.append("DUPLICATE_APPLICATION")
        return ReadinessResult(
            status=ReadinessStatus.BLOCKED,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 3. Duplicate suspected → REVIEW
    if duplicate_status == "DUPLICATE_SUSPECTED":
        reason_codes.append("DUPLICATE_SUSPECTED")
        return ReadinessResult(
            status=ReadinessStatus.REVIEW,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 4. Previous execution uncertain → REVIEW
    if previous_blockers:
        return ReadinessResult(
            status=ReadinessStatus.REVIEW,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 5. Contradictory data → REVIEW
    if contradictory:
        return ReadinessResult(
            status=ReadinessStatus.REVIEW,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 6. Ambiguous answers → REVIEW
    if ambiguous:
        return ReadinessResult(
            status=ReadinessStatus.REVIEW,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 7. Unsafe sensitive values → REVIEW
    if unsafe:
        return ReadinessResult(
            status=ReadinessStatus.REVIEW,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 8. Missing required fields → NEEDS_INPUT
    required_missing = [r for r in missing if r.required]
    if required_missing:
        return ReadinessResult(
            status=ReadinessStatus.NEEDS_INPUT,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 8b. Required documents invalid → BLOCKED
    required_invalid = [r for r in invalid if r.required]
    if required_invalid:
        return ReadinessResult(
            status=ReadinessStatus.BLOCKED,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 9. Package not approved → REVIEW
    if package_status == ReadinessStatus.REVIEW:
        return ReadinessResult(
            status=ReadinessStatus.REVIEW,
            completeness=completeness,
            required_count=required_count,
            satisfied_count=satisfied_count,
            missing_requirements=missing,
            invalid_requirements=invalid,
            ambiguous_requirements=ambiguous,
            contradictory_requirements=contradictory,
            sensitive_requirements=sensitive,
            all_requirements=requirements,
            package_status=package_status,
            preflight_status=preflight_status,
            duplicate_status=duplicate_status,
            previous_execution_blockers=previous_blockers,
            reason_codes=reason_codes,
        )

    # 10. All checks pass → READY
    return ReadinessResult(
        status=ReadinessStatus.READY,
        completeness=completeness,
        required_count=required_count,
        satisfied_count=satisfied_count,
        missing_requirements=missing,
        invalid_requirements=invalid,
        ambiguous_requirements=ambiguous,
        contradictory_requirements=contradictory,
        sensitive_requirements=sensitive,
        all_requirements=requirements,
        package_status=package_status,
        preflight_status=preflight_status,
        duplicate_status=duplicate_status,
        previous_execution_blockers=previous_blockers,
        reason_codes=reason_codes,
    )


# ---------------------------------------------------------------------------
# Main readiness check
# ---------------------------------------------------------------------------

def run_readiness_check(
    *,
    profile_data: dict | None = None,
    package_data: dict | None = None,
    resume_data: dict | None = None,
    form_fields: list[dict] | None = None,
    job_data: dict | None = None,
    answers: dict[str, str] | None = None,
    memory_answers: dict[str, str] | None = None,
    previous_executions: list[dict] | None = None,
    duplicate_status: str = "SAFE_TO_SUBMIT",
    application_id: int | None = None,
    job_id: int | None = None,
    package_id: int | None = None,
) -> ReadinessResult:
    """Run all readiness checks and produce a structured result.

    This is the main entry point for the readiness gate.
    Every check is deterministic — no LLM, no guessing.
    """
    # 1. Profile completeness (informational)
    completeness = evaluate_profile_completeness(profile_data)

    # 2. Detect application-specific requirements
    requirements_defs = detect_requirements_from_form_fields(form_fields, job_data)

    # 3. Build requirements and check each one
    requirements: list[Requirement] = []
    for req_def in requirements_defs:
        req = Requirement(
            category=req_def["category"],
            label=req_def["label"],
            source=req_def.get("source", "unknown"),
            is_sensitive=req_def.get("is_sensitive", False),
            is_document=req_def.get("is_document", False),
            document_type=req_def.get("document_type"),
            field_key=req_def.get("field_key"),
            required=req_def.get("required", False),
        )

        # Check answer readiness
        req = check_answer_readiness(req, profile_data, answers, memory_answers)

        # Check document readiness
        if req.is_document:
            req = check_document_readiness(req, package_data, resume_data)

        requirements.append(req)

    # 4. Detect profile conflicts
    contradictions = detect_profile_conflicts(profile_data, answers, memory_answers)
    requirements.extend(contradictions)

    # 5. Check package readiness
    pkg_status, pkg_reasons = check_package_readiness(package_data)

    # 6. Check previous execution blockers
    prev_blockers = check_previous_execution_blockers(previous_executions)

    # 7. Determine final readiness
    result = determine_readiness(
        requirements=requirements,
        completeness=completeness,
        package_status=pkg_status,
        preflight_status="PENDING",  # Will be filled by caller if needed
        duplicate_status=duplicate_status,
        previous_blockers=prev_blockers,
    )

    result.application_id = application_id
    result.job_id = job_id
    result.package_id = package_id

    return result


# ---------------------------------------------------------------------------
# Readiness refresh
# ---------------------------------------------------------------------------

def needs_refresh(
    result: ReadinessResult,
    *,
    max_age_seconds: int = 1800,  # 30 minutes
) -> bool:
    """Check if a readiness result is stale and needs recalculation.

    Returns True if the result is older than max_age_seconds.
    """
    if not result.checked_at:
        return True

    try:
        checked = datetime.fromisoformat(result.checked_at)
        now = datetime.now(timezone.utc)
        age = (now - checked).total_seconds()
        return age > max_age_seconds
    except (ValueError, TypeError):
        return True
