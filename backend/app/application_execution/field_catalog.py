"""Canonical field catalog for semantic field mapping (Phase 12).

Defines every recognized application field concept with aliases, sensitivity
level, and validation rules. The catalog is the single source of truth for
what fields exist and how they should be handled.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Sensitivity levels
# ---------------------------------------------------------------------------
SENSITIVITY_LOW = "LOW"
SENSITIVITY_MEDIUM = "MEDIUM"
SENSITIVITY_HIGH = "HIGH"

# ---------------------------------------------------------------------------
# Mapping methods
# ---------------------------------------------------------------------------
MAPPING_DETERMINISTIC = "DETERMINISTIC"
MAPPING_ALIAS = "ALIAS"
MAPPING_SEMANTIC = "SEMANTIC"
MAPPING_USER_VERIFIED = "USER_VERIFIED"

# ---------------------------------------------------------------------------
# Field categories
# ---------------------------------------------------------------------------
CATEGORY_PERSONAL = "PERSONAL"
CATEGORY_WORK = "WORK"
CATEGORY_EDUCATION = "EDUCATION"
CATEGORY_AUTHORIZATION = "AUTHORIZATION"
CATEGORY_APPLICATION = "APPLICATION"
CATEGORY_FILES = "FILES"


@dataclass
class FieldConcept:
    """A canonical field concept with all metadata."""

    canonical: str
    category: str
    aliases: list[str]
    sensitivity: str = SENSITIVITY_LOW
    input_types: tuple[str, ...] = ("text", "textarea", "select", "radio")
    validation: str | None = None  # email | phone | url | year | none
    description: str = ""


# ---------------------------------------------------------------------------
# Personal fields
# ---------------------------------------------------------------------------
PERSONAL_FIELDS = [
    FieldConcept(
        canonical="FIRST_NAME",
        category=CATEGORY_PERSONAL,
        aliases=[
            "first name", "first", "given name", "firstname",
            "candidate first name", "your first name", "fname",
        ],
        description="Given/first name",
    ),
    FieldConcept(
        canonical="LAST_NAME",
        category=CATEGORY_PERSONAL,
        aliases=[
            "last name", "last", "surname", "sur name", "family name",
            "candidate last name", "your last name", "lname",
        ],
        description="Family/last name",
    ),
    FieldConcept(
        canonical="FULL_NAME",
        category=CATEGORY_PERSONAL,
        aliases=[
            "full name", "fullname", "name", "your name",
            "candidate name", "applicant name", "complete name",
        ],
        description="Full legal name",
    ),
    FieldConcept(
        canonical="EMAIL",
        category=CATEGORY_PERSONAL,
        aliases=[
            "email", "email address", "e mail", "e-mail",
            "your email", "contact email", "work email", "personal email",
        ],
        validation="email",
        description="Email address",
    ),
    FieldConcept(
        canonical="PHONE",
        category=CATEGORY_PERSONAL,
        aliases=[
            "phone", "phone number", "mobile", "mobile number",
            "contact number", "telephone", "phone no", "cell phone",
            "cell number", "work phone", "home phone",
        ],
        validation="phone",
        description="Phone number",
    ),
    FieldConcept(
        canonical="LOCATION",
        category=CATEGORY_PERSONAL,
        aliases=[
            "location", "city", "current city", "current location",
            "city of residence", "where are you located",
        ],
        description="City/location",
    ),
    FieldConcept(
        canonical="STATE",
        category=CATEGORY_PERSONAL,
        aliases=[
            "state", "province", "region", "state/province",
        ],
        description="State or province",
    ),
    FieldConcept(
        canonical="COUNTRY",
        category=CATEGORY_PERSONAL,
        aliases=[
            "country", "country of residence", "residence",
            "country of citizenship", "nationality",
        ],
        input_types=("text", "select", "radio"),
        description="Country",
    ),
    FieldConcept(
        canonical="ADDRESS",
        category=CATEGORY_PERSONAL,
        aliases=[
            "address", "street address", "full address",
            "mailing address", "home address",
        ],
        description="Street address",
    ),
    FieldConcept(
        canonical="LINKEDIN_URL",
        category=CATEGORY_PERSONAL,
        aliases=[
            "linkedin url", "linkedin profile", "linkedin profile url",
            "linkedin", "linkedin link",
        ],
        validation="url",
        description="LinkedIn profile URL",
    ),
    FieldConcept(
        canonical="GITHUB_URL",
        category=CATEGORY_PERSONAL,
        aliases=[
            "github url", "github profile", "github",
            "github username", "github link",
        ],
        validation="url",
        description="GitHub profile URL",
    ),
    FieldConcept(
        canonical="PORTFOLIO_URL",
        category=CATEGORY_PERSONAL,
        aliases=[
            "portfolio url", "portfolio", "website",
            "personal website", "personal url", "portfolio link",
            "website url", "personal site",
        ],
        validation="url",
        description="Portfolio/personal website URL",
    ),
]

# ---------------------------------------------------------------------------
# Work fields
# ---------------------------------------------------------------------------
WORK_FIELDS = [
    FieldConcept(
        canonical="CURRENT_COMPANY",
        category=CATEGORY_WORK,
        aliases=[
            "current company", "employer", "company name",
            "current employer", "organization", "where do you work",
        ],
        description="Current employer",
    ),
    FieldConcept(
        canonical="YEARS_EXPERIENCE",
        category=CATEGORY_WORK,
        aliases=[
            "years of experience", "experience", "total experience",
            "experience level", "work experience", "years experience",
            "total years of experience", "professional experience",
        ],
        validation="year",
        description="Years of professional experience",
    ),
    FieldConcept(
        canonical="CURRENT_ROLE",
        category=CATEGORY_WORK,
        aliases=[
            "current role", "current position", "job title",
            "designation", "current designation", "role",
            "what is your current role",
        ],
        description="Current job title/role",
    ),
    FieldConcept(
        canonical="NOTICE_PERIOD",
        category=CATEGORY_WORK,
        aliases=[
            "notice period", "current notice period", "joining notice",
            "notice", "notice days", "how soon can you join",
        ],
        description="Notice period at current employer",
    ),
    FieldConcept(
        canonical="SALARY_EXPECTATION",
        category=CATEGORY_WORK,
        aliases=[
            "salary", "expected salary", "expected ctc",
            "salary expectation", "compensation", "annual salary",
            "expected compensation", "salary range",
        ],
        sensitivity=SENSITIVITY_MEDIUM,
        description="Expected salary/compensation",
    ),
    FieldConcept(
        canonical="CURRENT_CTC",
        category=CATEGORY_WORK,
        aliases=[
            "current ctc", "current salary", "current salary lpa",
            "current package", "monthly ctc", "current compensation",
        ],
        sensitivity=SENSITIVITY_MEDIUM,
        description="Current salary/CTC",
    ),
]

# ---------------------------------------------------------------------------
# Education fields
# ---------------------------------------------------------------------------
EDUCATION_FIELDS = [
    FieldConcept(
        canonical="DEGREE",
        category=CATEGORY_EDUCATION,
        aliases=[
            "degree", "qualification", "highest degree",
            "education level", "education", "highest qualification",
        ],
        input_types=("text", "select", "radio"),
        description="Degree/qualification",
    ),
    FieldConcept(
        canonical="UNIVERSITY",
        category=CATEGORY_EDUCATION,
        aliases=[
            "university", "college", "institution",
            "school name", " alma mater",
        ],
        description="University/institution name",
    ),
    FieldConcept(
        canonical="GRADUATION_YEAR",
        category=CATEGORY_EDUCATION,
        aliases=[
            "graduation year", "year of graduation", "pass out year",
            "passout year", "graduation date", "year completed",
        ],
        validation="year",
        input_types=("text", "date"),
        description="Year of graduation",
    ),
]

# ---------------------------------------------------------------------------
# Authorization fields
# ---------------------------------------------------------------------------
AUTHORIZATION_FIELDS = [
    FieldConcept(
        canonical="WORK_AUTHORIZATION",
        category=CATEGORY_AUTHORIZATION,
        aliases=[
            "work authorization", "work authorisation",
            "authorization to work", "right to work",
            "visa status", "are you authorized to work",
            "legally authorized", "work permit",
        ],
        sensitivity=SENSITIVITY_HIGH,
        input_types=("text", "select", "radio"),
        description="Work authorization status",
    ),
    FieldConcept(
        canonical="SPONSORSHIP_REQUIRED",
        category=CATEGORY_AUTHORIZATION,
        aliases=[
            "sponsorship", "visa sponsorship", "require sponsorship",
            "will you require sponsorship", "do you need sponsorship",
            "sponsorship required", "h1b", "h-1b",
        ],
        sensitivity=SENSITIVITY_HIGH,
        input_types=("select", "radio"),
        description="Whether visa sponsorship is required",
    ),
]

# ---------------------------------------------------------------------------
# Application fields
# ---------------------------------------------------------------------------
APPLICATION_FIELDS = [
    FieldConcept(
        canonical="COVER_LETTER",
        category=CATEGORY_APPLICATION,
        aliases=[
            "cover letter", "coverletter", "cover letter text",
            "why do you want this role", "motivation",
            "why are you interested", "tell us about yourself",
        ],
        input_types=("text", "textarea"),
        description="Cover letter or motivation text",
    ),
    FieldConcept(
        canonical="AVAILABILITY",
        category=CATEGORY_APPLICATION,
        aliases=[
            "availability", "start date", "available from",
            "when can you start", "earliest start date",
        ],
        input_types=("text", "date", "select"),
        description="Availability/start date",
    ),
    FieldConcept(
        canonical="REFERRAL",
        category=CATEGORY_APPLICATION,
        aliases=[
            "referral", "referral name", "how did you hear about us",
            "referral source", "employee referral",
        ],
        description="Referral information",
    ),
    FieldConcept(
        canonical="RELOCATION",
        category=CATEGORY_APPLICATION,
        aliases=[
            "relocation", "willing to relocate", "ready to relocate",
            "relocate", "open to relocation",
        ],
        sensitivity=SENSITIVITY_HIGH,
        input_types=("select", "radio"),
        description="Relocation willingness",
    ),
    FieldConcept(
        canonical="GENDER",
        category=CATEGORY_APPLICATION,
        aliases=[
            "gender", "sex", "gender identity",
        ],
        sensitivity=SENSITIVITY_HIGH,
        input_types=("select", "radio"),
        description="Gender (demographic)",
    ),
]

# ---------------------------------------------------------------------------
# File fields
# ---------------------------------------------------------------------------
FILE_FIELDS = [
    FieldConcept(
        canonical="RESUME",
        category=CATEGORY_FILES,
        aliases=[
            "resume", "cv", "upload cv", "upload resume",
            "attach resume", "attach cv", "resume file",
            "cv file", "upload your resume",
        ],
        input_types=("file",),
        description="Resume/CV file upload",
    ),
    FieldConcept(
        canonical="COVER_LETTER_FILE",
        category=CATEGORY_FILES,
        aliases=[
            "cover letter file", "cover letter upload",
            "upload cover letter", "attach cover letter",
        ],
        input_types=("file",),
        description="Cover letter file upload",
    ),
    FieldConcept(
        canonical="PORTFOLIO_FILE",
        category=CATEGORY_FILES,
        aliases=[
            "portfolio file", "work sample", "portfolio upload",
            "upload portfolio", "attachment", "supporting documents",
        ],
        input_types=("file",),
        description="Portfolio/work sample file",
    ),
    FieldConcept(
        canonical="CERTIFICATE_FILE",
        category=CATEGORY_FILES,
        aliases=[
            "certificate", "certification", "credential",
            "upload certificate", "attach certificate",
        ],
        input_types=("file",),
        description="Certificate/credential file upload",
    ),
]

# ---------------------------------------------------------------------------
# Advanced control fields (Phase 16)
# ---------------------------------------------------------------------------
ADVANCED_CONTROL_FIELDS = [
    FieldConcept(
        canonical="TERMS_ACCEPTANCE",
        category=CATEGORY_APPLICATION,
        aliases=[
            "terms", "terms and conditions", "i agree to the terms",
            "terms of service", "terms of use",
        ],
        input_types=("checkbox",),
        description="Terms and conditions acceptance checkbox",
    ),
    FieldConcept(
        canonical="DATA_CONSENT",
        category=CATEGORY_APPLICATION,
        aliases=[
            "consent", "data consent", "i consent",
            "data processing consent", "privacy consent",
        ],
        input_types=("checkbox",),
        description="Data processing consent checkbox",
    ),
    FieldConcept(
        canonical="EMPLOYMENT_TYPE",
        category=CATEGORY_WORK,
        aliases=[
            "employment type", "job type", "position type",
            "work type", "employment status",
        ],
        input_types=("select", "radio"),
        description="Employment type (full-time, part-time, contract)",
    ),
    FieldConcept(
        canonical="WORK_PREFERENCE",
        category=CATEGORY_WORK,
        aliases=[
            "work preference", "work mode", "work location",
            "remote preference", "hybrid", "on-site",
        ],
        input_types=("select", "radio"),
        description="Work location preference (remote, hybrid, on-site)",
    ),
    FieldConcept(
        canonical="SKILLS_MULTI",
        category=CATEGORY_WORK,
        aliases=[
            "skills", "skill set", "technical skills",
            "key skills", "preferred technologies",
        ],
        input_types=("multi_select", "text"),
        description="Skills (multi-select)",
    ),
    FieldConcept(
        canonical="AVAILABILITY_DATE",
        category=CATEGORY_APPLICATION,
        aliases=[
            "availability date", "start date", "available from",
            "earliest start date", "when can you start",
        ],
        input_types=("date", "text"),
        description="Availability/start date",
    ),
    FieldConcept(
        canonical="GRADUATION_DATE",
        category=CATEGORY_EDUCATION,
        aliases=[
            "graduation date", "date of graduation", "graduation",
            "when did you graduate",
        ],
        input_types=("date", "text"),
        description="Graduation date",
    ),
    FieldConcept(
        canonical="EXPECTED_SALARY",
        category=CATEGORY_WORK,
        aliases=[
            "expected salary", "desired compensation", "salary expectation",
            "expected ctc", "compensation", "annual salary",
        ],
        sensitivity=SENSITIVITY_MEDIUM,
        input_types=("currency", "text"),
        description="Expected salary/compensation",
    ),
    FieldConcept(
        canonical="CITY_LOCATION",
        category=CATEGORY_PERSONAL,
        aliases=[
            "city", "current city", "location", "city/location",
        ],
        input_types=("autocomplete", "text", "select"),
        description="City/location (autocomplete)",
    ),
    FieldConcept(
        canonical="UNIVERSITY_LOCATION",
        category=CATEGORY_EDUCATION,
        aliases=[
            "university", "college", "institution",
        ],
        input_types=("autocomplete", "text", "select"),
        description="University/institution (autocomplete)",
    ),
    FieldConcept(
        canonical="COMPANY_NAME",
        category=CATEGORY_WORK,
        aliases=[
            "company", "current company", "company name",
            "employer", "employer name",
        ],
        input_types=("autocomplete", "text"),
        description="Company name (autocomplete)",
    ),
]

# ---------------------------------------------------------------------------
# Complete catalog
# ---------------------------------------------------------------------------
ALL_FIELD_CONCEPTS: list[FieldConcept] = (
    PERSONAL_FIELDS
    + WORK_FIELDS
    + EDUCATION_FIELDS
    + AUTHORIZATION_FIELDS
    + APPLICATION_FIELDS
    + FILE_FIELDS
    + ADVANCED_CONTROL_FIELDS
)

# Index: canonical -> concept
CONCEPT_BY_CANONICAL: dict[str, FieldConcept] = {
    c.canonical: c for c in ALL_FIELD_CONCEPTS
}

# Index: normalized alias -> canonical
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _concept in ALL_FIELD_CONCEPTS:
    for _alias in _concept.aliases:
        _normalized = " ".join(_alias.lower().split())
        _ALIAS_TO_CANONICAL.setdefault(_normalized, _concept.canonical)

# Sensitivity index
SENSITIVITY_BY_CANONICAL: dict[str, str] = {
    c.canonical: c.sensitivity for c in ALL_FIELD_CONCEPTS
}

# Category index
CATEGORY_BY_CANONICAL: dict[str, str] = {
    c.canonical: c.category for c in ALL_FIELD_CONCEPTS
}


def lookup_concept(label: str) -> FieldConcept | None:
    """Look up a field concept by label text."""
    normalized = " ".join(label.lower().split())
    canonical = _ALIAS_TO_CANONICAL.get(normalized)
    if canonical:
        return CONCEPT_BY_CANONICAL[canonical]
    # Token-based fallback: check if any alias is a subset of the label tokens
    label_tokens = set(normalized.split())
    for concept in ALL_FIELD_CONCEPTS:
        for alias in concept.aliases:
            alias_tokens = set(alias.lower().split())
            if alias_tokens and alias_tokens <= label_tokens:
                return concept
    return None


def get_sensitivity(canonical: str) -> str:
    """Get sensitivity level for a canonical field."""
    return SENSITIVITY_BY_CANONICAL.get(canonical, SENSITIVITY_LOW)


def get_category(canonical: str) -> str:
    """Get category for a canonical field."""
    return CATEGORY_BY_CANONICAL.get(canonical, CATEGORY_PERSONAL)
