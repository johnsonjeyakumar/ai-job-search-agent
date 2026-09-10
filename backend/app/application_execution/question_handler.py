"""Question normalization and handling (Phase 12 + Phase 21).

Normalizes application questions for reuse, handles unknown questions,
and enforces sensitive question policy. Questions are normalized
deterministically without LLM involvement.

Phase 21 adds:
- Expanded question categories (knockout, demographic, declaration, etc.)
- Knockout question detection
- Work authorization / sponsorship handling
- Experience requirement comparison
- Sensitive question classification
- Declaration / attestation / consent handling
- Electronic signature detection
- Answer source priority
- Confidence states
- Contradiction detection
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.application_execution.memory import (
    ANSWER_TYPE_BOOLEAN,
    ANSWER_TYPE_SELECT,
    ANSWER_TYPE_TEXT,
    QUESTION_CATEGORY_AUTHORIZATION,
    QUESTION_CATEGORY_AVAILABILITY,
    QUESTION_CATEGORY_EXPERIENCE,
    QUESTION_CATEGORY_PERSONAL,
    QUESTION_CATEGORY_SALARY,
    QUESTION_CATEGORY_UNKNOWN,
    MemoryStore,
    _norm,
    _tokens,
)

# ---------------------------------------------------------------------------
# Question class (deterministic classification for safety routing)
# ---------------------------------------------------------------------------

class QuestionClass(str, Enum):
    """Deterministic classification for safety routing."""

    NORMAL = "NORMAL"
    KNOCKOUT = "KNOCKOUT"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    SPONSORSHIP = "SPONSORSHIP"
    EXPERIENCE_REQUIREMENT = "EXPERIENCE_REQUIREMENT"
    RELOCATION = "RELOCATION"
    AVAILABILITY = "AVAILABILITY"
    COMPENSATION = "COMPENSATION"
    SENSITIVE = "SENSITIVE"
    LEGAL_DECLARATION = "LEGAL_DECLARATION"
    ATTESTATION = "ATTESTATION"
    CONSENT = "CONSENT"
    E_SIGNATURE = "E_SIGNATURE"
    DEMOGRAPHIC = "DEMOGRAPHIC"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Answer confidence states
# ---------------------------------------------------------------------------

class AnswerConfidence(str, Enum):
    """Confidence states for answer resolution."""

    VERIFIED = "VERIFIED"               # Explicit user-verified answer
    DERIVED_VERIFIED = "DERIVED_VERIFIED"  # Derived from verified structured data
    AMBIGUOUS = "AMBIGUOUS"             # Multiple possible interpretations
    MISSING = "MISSING"                 # No answer found
    UNSAFE = "UNSAFE"                   # Answer exists but safety check fails
    CONTRADICTORY = "CONTRADICTORY"     # Data sources conflict


# ---------------------------------------------------------------------------
# Question concepts (canonical question forms) — expanded Phase 21
# ---------------------------------------------------------------------------

QUESTION_CONCEPTS: dict[str, dict] = {
    # Work authorization
    "work_authorization": {
        "canonical": "Are you authorized to work in this country?",
        "aliases": [
            "are you authorized to work",
            "are you legally authorized to work",
            "do you have work authorization",
            "are you permitted to work",
            "do you have the right to work",
            "are you authorized to work in the united states",
            "can you work in the us",
            "are you authorized to work in this country",
            "do you have the right to work in this country",
            "do you have work authorization in this country",
        ],
        "category": QUESTION_CATEGORY_AUTHORIZATION,
        "sensitivity": "HIGH",
        "question_class": QuestionClass.WORK_AUTHORIZATION,
    },
    # Sponsorship
    "sponsorship_required": {
        "canonical": "Will you require visa sponsorship?",
        "aliases": [
            "will you require sponsorship",
            "do you need sponsorship",
            "will sponsorship be required",
            "do you require visa sponsorship",
            "will you need h1b sponsorship",
            "will you now or in the future require sponsorship",
            "do you need visa sponsorship now or in the future",
        ],
        "category": QUESTION_CATEGORY_AUTHORIZATION,
        "sensitivity": "HIGH",
        "question_class": QuestionClass.SPONSORSHIP,
    },
    "future_sponsorship": {
        "canonical": "Will you require sponsorship in the future?",
        "aliases": [
            "will you need sponsorship in the future",
            "do you anticipate needing sponsorship",
            "will you require future sponsorship",
        ],
        "category": QUESTION_CATEGORY_AUTHORIZATION,
        "sensitivity": "HIGH",
        "question_class": QuestionClass.SPONSORSHIP,
    },
    # Relocation
    "relocation_willing": {
        "canonical": "Are you willing to relocate?",
        "aliases": [
            "willing to relocate",
            "can you relocate",
            "are you willing to relocate for this position",
            "would you be willing to relocate",
            "are you open to relocation",
            "can you work from another location",
        ],
        "category": QUESTION_CATEGORY_PERSONAL,
        "sensitivity": "HIGH",
        "question_class": QuestionClass.RELOCATION,
    },
    # Availability
    "availability_immediate": {
        "canonical": "Are you available to start immediately?",
        "aliases": [
            "can you start immediately",
            "are you available to work immediately",
            "when can you start",
            "what is your availability",
            "available to start",
            "start date",
        ],
        "category": QUESTION_CATEGORY_AVAILABILITY,
        "sensitivity": "LOW",
        "question_class": QuestionClass.AVAILABILITY,
    },
    # Compensation
    "salary_expectation": {
        "canonical": "What is your expected salary?",
        "aliases": [
            "expected salary",
            "salary expectation",
            "desired compensation",
            "what are your salary expectations",
            "salary requirements",
            "compensation expectations",
        ],
        "category": QUESTION_CATEGORY_SALARY,
        "sensitivity": "MEDIUM",
        "question_class": QuestionClass.COMPENSATION,
    },
    # Experience requirements (knockout potential)
    "years_experience": {
        "canonical": "How many years of experience do you have?",
        "aliases": [
            "years of experience",
            "how many years of experience",
            "experience level",
            "years of relevant experience",
        ],
        "category": QUESTION_CATEGORY_EXPERIENCE,
        "sensitivity": "LOW",
        "question_class": QuestionClass.EXPERIENCE_REQUIREMENT,
    },
}


# ---------------------------------------------------------------------------
# Knockout detection patterns
# ---------------------------------------------------------------------------

_KNOCKOUT_PATTERNS = [
    # Work authorization knockouts
    r"(?:are you|can you|do you)\s+(?:legally\s+)?(?:authorized|permitted|eligible)\s+to\s+work",
    r"(?:do you have|possess)\s+(?:valid\s+)?(?:work\s+)?(?:authorization|visa|permit|visa status)",
    r"(?:will you now or in the future)\s+require\s+(?:visa\s+)?sponsorship",
    r"(?:do you require|need)\s+(?:visa\s+)?sponsorship",
    # Experience knockouts
    r"(?:do you have|can you demonstrate)\s+(?:at least\s+)?"
    r"(\d+)\+?\s+years?\s+(?:of\s+)?(?:experience|expertise)",
    r"(?:have you worked|experience)\s+(?:with|in)\s+\w+"
    r"\s+for\s+(?:at least\s+)?(\d+)\s+years?",
    # Availability knockouts
    r"(?:can you|are you able to)\s+(?:work\s+)?"
    r"(?:weekends?|nights?|overtime|on-call|full[- ]time)",
    r"(?:are you available|can you start)\s+"
    r"(?:immediately|right away|within\s+\d+\s+(?:days?|weeks?))",
    # Relocation knockouts
    r"relocat\w*\s+to\s+[\w\s]+",
    r"(?:do you have|possess)\s+a\s+valid\s+(?:driver'?s?\s+)?licen[sc]e",
    # Legal / compliance knockouts
    r"(?:have you ever|do you have)\s+(?:been convicted|criminal|felony|misdemeanor)",
    r"(?:are you able to|can you)\s+(?:pass|complete)\s+"
    r"(?:a\s+)?(?:background\s+check|drug\s+test)",
]

_KNOCKOUT_RE = [re.compile(p, re.IGNORECASE) for p in _KNOCKOUT_PATTERNS]

# Declaration / attestation patterns
_DECLARATION_PATTERNS = [
    r"i\s+(?:hereby\s+)?(?:certify|confirm|attest|declare)",
    r"(?:i\s+)?(?:acknowledge|understand)\s+that",
    r"the\s+(?:information|data)\s+(?:provided|above|submitted)\s+is\s+(?:true|accurate|correct)",
    r"(?:i\s+)?agree\s+to\s+the\s+(?:terms|privacy|policy|conditions)",
    r"(?:i\s+)?consent\s+to",
    r"(?:electronic|digital)\s+signature",
    r"type\s+(?:your\s+)?(?:full\s+)?(?:legal\s+)?name\s+(?:below|here|as\s+your\s+signature)",
]

_DECLARATION_RE = [re.compile(p, re.IGNORECASE) for p in _DECLARATION_PATTERNS]

# Signature patterns
_SIGNATURE_PATTERNS = [
    r"(?:electronic|digital)\s+signature",
    r"type\s+(?:your\s+)?(?:full\s+)?(?:legal\s+)?name",
    r"sign(?:ature)?\s+(?:below|here|field|box)",
    r"(?:sign|enter)\s+(?:your\s+)?(?:full\s+)?name\s+(?:here|below|as\s+your)",
]

_SIGNATURE_RE = [re.compile(p, re.IGNORECASE) for p in _SIGNATURE_PATTERNS]

# Consent patterns
_REQUIRED_CONSENT_PATTERNS = [
    r"i\s+agree\s+to\s+the\s+(?:application\s+)?(?:privacy\s+)?(?:notice|policy|terms)",
    r"(?:i\s+)?(?:consent|agree)\s+to\s+the\s+(?:processing|collection)\s+of\s+(?:my\s+)?(?:personal\s+)?data",
    r"(?:i\s+)?acknowledge\s+the\s+(?:privacy|data\s+protection|terms)",
]

_OPTIONAL_CONSENT_PATTERNS = [
    r"(?:i\s+)?(?:agree|consent)\s+to\s+(?:receive\s+)?"
    r"(?:marketing|promotional|news(?:letter)?|updates?)",
    r"(?:i\s+)?opt[\s-]+in\s+to\s+(?:receive\s+)?(?:marketing|promotional)",
    r"(?:keep me|add me)\s+(?:informed|updated)\s+about\s+"
    r"(?:new\s+)?(?:jobs?|positions?|opportunities?)",
]

_REQUIRED_CONSENT_RE = [re.compile(p, re.IGNORECASE) for p in _REQUIRED_CONSENT_PATTERNS]
_OPTIONAL_CONSENT_RE = [re.compile(p, re.IGNORECASE) for p in _OPTIONAL_CONSENT_PATTERNS]

# Demographic patterns
_DEMOGRAPHIC_PATTERNS = [
    r"what\s+is\s+your\s+(?:gender|race|ethnicity|religion|nationality|sexual\s+orientation|marital\s+status)",
    r"(?:are you|do you\s+identify\s+as)\s+(?:a\s+)?(?:veteran|military|disabled|pregnant)",
    r"(?:do you have|are you\s+(?:a\s+)?person\s+with)\s+(?:a\s+)?disability",
    r"(?:what|your)\s+(?:date\s+of\s+birth|dob|age|citizenship)",
]

_DEMOGRAPHIC_RE = [re.compile(p, re.IGNORECASE) for p in _DEMOGRAPHIC_PATTERNS]


@dataclass
class QuestionClassification:
    """Classification of an application question."""

    raw_question: str
    normalized: str
    category: str = QUESTION_CATEGORY_UNKNOWN
    sensitivity: str = "LOW"
    is_known_concept: bool = False
    concept_key: str | None = None
    answer_type: str = ANSWER_TYPE_TEXT
    available_options: list[str] = field(default_factory=list)
    question_class: str = QuestionClass.UNKNOWN.value
    is_knockout: bool = False
    is_declaration: bool = False
    is_signature: bool = False
    is_consent: bool = False
    is_required_consent: bool = False
    is_optional_consent: bool = False
    is_demographic: bool = False
    requires_explicit_answer: bool = False


@dataclass
class QuestionHandlingResult:
    """Result of processing an application question."""

    classification: QuestionClassification
    answer: str | None = None
    source: str | None = None
    verification_status: str | None = None
    confidence: str = AnswerConfidence.MISSING.value
    needs_user_input: bool = False
    is_blocked: bool = False
    block_reason: str | None = None
    warning: str | None = None
    question_class: str = QuestionClass.UNKNOWN.value
    is_knockout: bool = False
    does_not_meet: bool = False


def classify_question(
    raw_question: str,
    available_options: list[str] | None = None,
) -> QuestionClassification:
    """Classify an application question deterministically."""
    normalized = _norm(raw_question)
    options = available_options or []

    # Check for demographic questions FIRST (before concept matching)
    is_demographic = _detect_demographic(normalized)

    # Check known question concepts (expanded)
    _KNOCKOUT_CLASSES = {
        QuestionClass.WORK_AUTHORIZATION,
        QuestionClass.SPONSORSHIP,
        QuestionClass.EXPERIENCE_REQUIREMENT,
        QuestionClass.RELOCATION,
        QuestionClass.KNOCKOUT,
    }
    for concept_key, concept in QUESTION_CONCEPTS.items():
        for alias in concept["aliases"]:
            if _norm(alias) == normalized or _semantic_match(normalized, _norm(alias)):
                concept_qc = concept.get("question_class", QuestionClass.NORMAL)
                # Demographic questions override concept classification
                if is_demographic:
                    concept_qc = QuestionClass.DEMOGRAPHIC
                return QuestionClassification(
                    raw_question=raw_question,
                    normalized=normalized,
                    category=concept["category"],
                    sensitivity="HIGH" if is_demographic else concept["sensitivity"],
                    is_known_concept=True,
                    concept_key=concept_key,
                    answer_type=_detect_answer_type(options),
                    available_options=options,
                    question_class=concept_qc.value,
                    is_knockout=concept_qc in _KNOCKOUT_CLASSES and not is_demographic,
                    is_demographic=is_demographic,
                )

    # Check for knockout patterns
    is_knockout = _detect_knockout(normalized)

    # Check for declaration / attestation
    is_declaration = _detect_declaration(normalized)

    # Check for signature
    is_signature = _detect_signature(normalized)

    # Check for consent
    is_required_consent, is_optional_consent = _detect_consent(normalized)

    # Check for demographic
    is_demographic = _detect_demographic(normalized)

    # Classify by content (expanded)
    category = _classify_by_content(normalized)
    sensitivity = _classify_sensitivity(normalized)

    # Determine question class
    question_class = _determine_question_class(
        normalized, category, sensitivity, is_knockout, is_declaration,
        is_signature, is_required_consent, is_optional_consent, is_demographic,
    )

    return QuestionClassification(
        raw_question=raw_question,
        normalized=normalized,
        category=category,
        sensitivity=sensitivity,
        is_known_concept=False,
        answer_type=_detect_answer_type(options),
        available_options=options,
        question_class=question_class,
        is_knockout=is_knockout,
        is_declaration=is_declaration,
        is_signature=is_signature,
        is_consent=is_required_consent or is_optional_consent,
        is_required_consent=is_required_consent,
        is_optional_consent=is_optional_consent,
        is_demographic=is_demographic,
        requires_explicit_answer=is_knockout or is_signature or is_declaration,
    )


def handle_question(
    question: str,
    memory: MemoryStore,
    available_options: list[str] | None = None,
    job_context: dict | None = None,
    profile_context: dict | None = None,
) -> QuestionHandlingResult:
    """Handle an application question using memory and context.

    Decision flow:
    1. Classify question
    2. Check memory for verified answer
    3. Apply sensitivity policy
    4. Return result with answer or request for user input
    """
    classification = classify_question(question, available_options)

    # Knockout questions must have verified answer
    if classification.is_knockout:
        verified_answer = memory.get_verified_answer(question)
        if verified_answer:
            return QuestionHandlingResult(
                classification=classification,
                answer=verified_answer.answer,
                source=verified_answer.source,
                verification_status=verified_answer.verification_status,
                confidence=AnswerConfidence.VERIFIED.value,
                needs_user_input=False,
                is_blocked=False,
                question_class=classification.question_class,
                is_knockout=True,
            )
        return QuestionHandlingResult(
            classification=classification,
            answer=None,
            confidence=AnswerConfidence.MISSING.value,
            needs_user_input=True,
            is_blocked=False,
            warning="Knockout question requires verified answer.",
            question_class=classification.question_class,
            is_knockout=True,
        )

    # Signature questions must have verified value
    if classification.is_signature:
        verified_answer = memory.get_verified_answer(question)
        if verified_answer:
            return QuestionHandlingResult(
                classification=classification,
                answer=verified_answer.answer,
                source=verified_answer.source,
                verification_status=verified_answer.verification_status,
                confidence=AnswerConfidence.VERIFIED.value,
                needs_user_input=False,
                is_blocked=False,
                question_class=classification.question_class,
            )
        return QuestionHandlingResult(
            classification=classification,
            answer=None,
            confidence=AnswerConfidence.MISSING.value,
            needs_user_input=True,
            is_blocked=True,
            block_reason="Electronic signature requires verified value and explicit policy.",
            question_class=classification.question_class,
        )

    # Optional marketing consent — do NOT auto-enable (before declaration check)
    if classification.is_optional_consent:
        return QuestionHandlingResult(
            classification=classification,
            answer="No",
            source="policy.default",
            verification_status="POLICY_DEFAULT",
            confidence=AnswerConfidence.VERIFIED.value,
            needs_user_input=False,
            is_blocked=False,
            warning="Optional marketing consent defaults to No unless explicitly enabled.",
            question_class=classification.question_class,
        )

    # Declarations require explicit authorization
    if classification.is_declaration:
        verified_answer = memory.get_verified_answer(question)
        if verified_answer:
            return QuestionHandlingResult(
                classification=classification,
                answer=verified_answer.answer,
                source=verified_answer.source,
                verification_status=verified_answer.verification_status,
                confidence=AnswerConfidence.VERIFIED.value,
                needs_user_input=False,
                is_blocked=False,
                question_class=classification.question_class,
            )
        return QuestionHandlingResult(
            classification=classification,
            answer=None,
            confidence=AnswerConfidence.MISSING.value,
            needs_user_input=True,
            is_blocked=False,
            warning="Declaration requires explicit user authorization.",
            question_class=classification.question_class,
        )

    # Optional marketing consent — do NOT auto-enable
    if classification.is_optional_consent:
        return QuestionHandlingResult(
            classification=classification,
            answer="No",
            source="policy.default",
            verification_status="POLICY_DEFAULT",
            confidence=AnswerConfidence.VERIFIED.value,
            needs_user_input=False,
            is_blocked=False,
            warning="Optional marketing consent defaults to No unless explicitly enabled.",
            question_class=classification.question_class,
        )

    # Demographic questions — never infer
    if classification.is_demographic:
        verified_answer = memory.get_verified_answer(question)
        if verified_answer:
            return QuestionHandlingResult(
                classification=classification,
                answer=verified_answer.answer,
                source=verified_answer.source,
                verification_status=verified_answer.verification_status,
                confidence=AnswerConfidence.VERIFIED.value,
                needs_user_input=False,
                is_blocked=False,
                question_class=classification.question_class,
            )
        return QuestionHandlingResult(
            classification=classification,
            answer=None,
            confidence=AnswerConfidence.MISSING.value,
            needs_user_input=True,
            is_blocked=False,
            warning="Demographic question requires explicit user-provided value.",
            question_class=classification.question_class,
        )

    # Check memory for verified answer
    verified_answer = memory.get_verified_answer(question)
    if verified_answer:
        return QuestionHandlingResult(
            classification=classification,
            answer=verified_answer.answer,
            source=verified_answer.source,
            verification_status=verified_answer.verification_status,
            confidence=AnswerConfidence.VERIFIED.value,
            needs_user_input=False,
            is_blocked=False,
            question_class=classification.question_class,
        )

    # Check memory for any answer (not just verified)
    any_answer = memory.get_answer(question)
    if any_answer and classification.sensitivity == "LOW":
        return QuestionHandlingResult(
            classification=classification,
            answer=any_answer.answer,
            source=any_answer.source,
            verification_status=any_answer.verification_status,
            confidence=AnswerConfidence.DERIVED_VERIFIED.value,
            needs_user_input=False,
            is_blocked=False,
            warning="Using unverified answer for low-sensitivity field.",
            question_class=classification.question_class,
        )

    # High sensitivity without verified answer -> must ask user
    if classification.sensitivity == "HIGH":
        return QuestionHandlingResult(
            classification=classification,
            answer=None,
            confidence=AnswerConfidence.MISSING.value,
            needs_user_input=True,
            is_blocked=False,
            warning="Sensitive question requires explicit user verification.",
            question_class=classification.question_class,
        )

    # Unknown question -> ask user
    return QuestionHandlingResult(
        classification=classification,
        answer=None,
        confidence=AnswerConfidence.MISSING.value,
        needs_user_input=True,
        is_blocked=False,
        question_class=classification.question_class,
    )


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def _detect_answer_type(options: list[str]) -> str:
    """Detect answer type from available options."""
    if not options:
        return ANSWER_TYPE_TEXT

    options_lower = [o.lower().strip() for o in options]

    # Boolean detection
    boolean_sets = [
        {"yes", "no"},
        {"true", "false"},
        {"1", "0"},
    ]
    for bool_set in boolean_sets:
        if set(options_lower) == bool_set:
            return ANSWER_TYPE_BOOLEAN

    return ANSWER_TYPE_SELECT


def _detect_knockout(normalized: str) -> bool:
    """Detect if a question is a knockout/disqualifying question."""
    for pattern in _KNOCKOUT_RE:
        if pattern.search(normalized):
            return True
    return False


def _detect_declaration(normalized: str) -> bool:
    """Detect if a question is a declaration/attestation."""
    for pattern in _DECLARATION_RE:
        if pattern.search(normalized):
            return True
    return False


def _detect_signature(normalized: str) -> bool:
    """Detect if a question is an electronic signature."""
    for pattern in _SIGNATURE_RE:
        if pattern.search(normalized):
            return True
    return False


def _detect_consent(normalized: str) -> tuple[bool, bool]:
    """Detect consent type. Returns (is_required, is_optional)."""
    is_required = False
    is_optional = False
    for pattern in _REQUIRED_CONSENT_RE:
        if pattern.search(normalized):
            is_required = True
            break
    for pattern in _OPTIONAL_CONSENT_RE:
        if pattern.search(normalized):
            is_optional = True
            break
    return is_required, is_optional


def _detect_demographic(normalized: str) -> bool:
    """Detect if a question is a demographic question."""
    for pattern in _DEMOGRAPHIC_RE:
        if pattern.search(normalized):
            return True
    return False


def _determine_question_class(
    normalized: str,
    category: str,
    sensitivity: str,
    is_knockout: bool,
    is_declaration: bool,
    is_signature: bool,
    is_required_consent: bool,
    is_optional_consent: bool,
    is_demographic: bool,
) -> str:
    """Determine the question class for safety routing."""
    if is_knockout:
        return QuestionClass.KNOCKOUT.value
    if is_signature:
        return QuestionClass.E_SIGNATURE.value
    # Consent before declaration (consent questions often contain "agree/consent")
    if is_required_consent or is_optional_consent:
        return QuestionClass.CONSENT.value
    if is_declaration:
        return QuestionClass.LEGAL_DECLARATION.value
    if is_demographic:
        return QuestionClass.DEMOGRAPHIC.value

    # Category-based classification
    category_map = {
        QUESTION_CATEGORY_AUTHORIZATION: _classify_auth_subclass(normalized),
        "SALARY": QuestionClass.COMPENSATION.value,
        "EXPERIENCE": QuestionClass.EXPERIENCE_REQUIREMENT.value,
        "AVAILABILITY": QuestionClass.AVAILABILITY.value,
        "PERSONAL": _classify_personal_subclass(normalized),
    }
    if category in category_map:
        return category_map[category]

    if sensitivity == "HIGH":
        return QuestionClass.SENSITIVE.value
    if sensitivity == "MEDIUM":
        return QuestionClass.COMPENSATION.value

    return QuestionClass.NORMAL.value


def _classify_auth_subclass(normalized: str) -> str:
    """Classify authorization questions into work authorization or sponsorship."""
    if any(kw in normalized for kw in ["sponsorship", "visa sponsorship", "h1b"]):
        return QuestionClass.SPONSORSHIP.value
    return QuestionClass.WORK_AUTHORIZATION.value


def _classify_personal_subclass(normalized: str) -> str:
    """Classify personal questions into relocation or normal."""
    if any(kw in normalized for kw in ["relocat", "move to", "another location"]):
        return QuestionClass.RELOCATION.value
    return QuestionClass.NORMAL.value


def _classify_by_content(question: str) -> str:
    """Classify question category by content analysis (expanded)."""
    from app.application_execution.memory import (
        QUESTION_CATEGORY_MOTIVATION,
        QUESTION_CATEGORY_TECHNICAL,
    )

    q = question.lower()

    # Consent (check before declaration to avoid false positives)
    is_req_consent, is_opt_consent = _detect_consent(q)
    if is_req_consent or is_opt_consent:
        return "CONSENT"

    # Declaration / attestation
    if _detect_declaration(q):
        return "LEGAL_DECLARATION"

    # Demographic
    if _detect_demographic(q):
        return "DEMOGRAPHIC"

    # Authorization
    if any(kw in q for kw in ["authorized", "authorization", "visa", "legal"]):
        return QUESTION_CATEGORY_AUTHORIZATION

    # Sponsorship
    if "sponsorship" in q:
        return QUESTION_CATEGORY_AUTHORIZATION

    # Salary / compensation
    if any(kw in q for kw in ["salary", "compensation", "ctc", "pay", "wage", "package"]):
        return QUESTION_CATEGORY_SALARY

    # Experience
    if any(kw in q for kw in ["experience", "years of", "background", "history", "worked"]):
        return QUESTION_CATEGORY_EXPERIENCE

    # Availability
    avail_kws = ["available", "availability", "start date", "join date", "notice period"]
    if any(kw in q for kw in avail_kws):
        return QUESTION_CATEGORY_AVAILABILITY

    # Relocation
    if any(kw in q for kw in ["relocat", "move to", "another location"]):
        return QUESTION_CATEGORY_PERSONAL

    # Motivation
    if any(kw in q for kw in ["why", "motivation", "interested", "want", "reason"]):
        return QUESTION_CATEGORY_MOTIVATION

    # Personal
    if any(kw in q for kw in ["name", "email", "phone", "address", "location", "city"]):
        return QUESTION_CATEGORY_PERSONAL

    # Technical
    if any(kw in q for kw in ["skill", "technology", "programming", "language", "framework"]):
        return QUESTION_CATEGORY_TECHNICAL

    return QUESTION_CATEGORY_UNKNOWN


def _classify_sensitivity(question: str) -> str:
    """Classify question sensitivity."""
    from app.application_execution.memory import _SENSITIVE_KEYWORDS

    q = question.lower()
    for keyword in _SENSITIVE_KEYWORDS:
        if keyword in q:
            return "HIGH"

    salary_keywords = {"salary", "compensation", "ctc", "pay", "wage", "package"}
    if any(kw in q for kw in salary_keywords):
        return "MEDIUM"

    return "LOW"


def _semantic_match(q1: str, q2: str) -> bool:
    """Check if two questions are semantically similar."""
    t1 = _tokens(q1)
    t2 = _tokens(q2)
    if not t1 or not t2:
        return False
    overlap = len(t1 & t2)
    return overlap / max(len(t1), len(t2)) >= 0.75


# ---------------------------------------------------------------------------
# Experience requirement comparison
# ---------------------------------------------------------------------------

def compare_experience_requirement(
    question: str,
    verified_years: float | None,
    verified_skills: list[str] | None = None,
) -> tuple[str, str]:
    """Compare applicant experience against a knockout requirement.

    Returns (result, detail) where result is one of:
    - "SAFE" — applicant meets the requirement
    - "DOES_NOT_MEET" — applicant does not meet the requirement
    - "UNKNOWN" — cannot determine
    """
    if verified_years is None:
        return "UNKNOWN", "No verified experience data available."

    # Extract required years from question
    required_match = re.search(r"(\d+)\+?\s*years?", question.lower())
    if not required_match:
        return "UNKNOWN", "Cannot extract required years from question."

    required_years = float(required_match.group(1))

    # Check for specific skill requirement
    skill_keywords = [
        "python", "java", "javascript", "typescript", "react", "angular",
        "vue", "node", "django", "flask", "aws", "azure", "gcp",
        "docker", "kubernetes", "sql", "nosql", "machine learning",
        "data science", "devops", "ci/cd", "git", "linux", "agile",
    ]

    required_skill = None
    for skill in skill_keywords:
        if skill in question.lower():
            required_skill = skill
            break

    # If specific skill mentioned, check if applicant has it
    if required_skill and verified_skills:
        has_skill = any(required_skill in s.lower() for s in verified_skills)
        if not has_skill:
            return "DOES_NOT_MEET", f"Applicant does not have {required_skill} experience."

    # Compare years
    if verified_years >= required_years:
        msg = (
            f"Applicant has {verified_years} years, "
            f"requirement is {required_years} years."
        )
        return "SAFE", msg

    return "DOES_NOT_MEET", (
        f"Applicant has {verified_years} years, "
        f"requirement is {required_years} years."
    )
