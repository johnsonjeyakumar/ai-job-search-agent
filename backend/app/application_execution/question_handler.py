"""Question normalization and handling (Phase 12).

Normalizes application questions for reuse, handles unknown questions,
and enforces sensitive question policy. Questions are normalized
deterministically without LLM involvement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.application_execution.memory import (
    ANSWER_TYPE_BOOLEAN,
    ANSWER_TYPE_SELECT,
    ANSWER_TYPE_TEXT,
    QUESTION_CATEGORY_AUTHORIZATION,
    QUESTION_CATEGORY_UNKNOWN,
    MemoryStore,
    _norm,
    _tokens,
)

# ---------------------------------------------------------------------------
# Question concepts (canonical question forms)
# ---------------------------------------------------------------------------

QUESTION_CONCEPTS: dict[str, dict] = {
    "work_authorization": {
        "canonical": "Are you authorized to work in this country?",
        "aliases": [
            "are you authorized to work",
            "are you legally authorized to work",
            "do you have work authorization",
            "are you permitted to work",
            "do you have the right to work",
        ],
        "category": QUESTION_CATEGORY_AUTHORIZATION,
        "sensitivity": "HIGH",
    },
    "sponsorship_required": {
        "canonical": "Will you require visa sponsorship?",
        "aliases": [
            "will you require sponsorship",
            "do you need sponsorship",
            "will sponsorship be required",
            "do you require visa sponsorship",
            "will you need h1b sponsorship",
        ],
        "category": QUESTION_CATEGORY_AUTHORIZATION,
        "sensitivity": "HIGH",
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
    },
}


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


@dataclass
class QuestionHandlingResult:
    """Result of processing an application question."""

    classification: QuestionClassification
    answer: str | None = None
    source: str | None = None
    verification_status: str | None = None
    needs_user_input: bool = False
    is_blocked: bool = False
    block_reason: str | None = None
    warning: str | None = None


def classify_question(
    raw_question: str,
    available_options: list[str] | None = None,
) -> QuestionClassification:
    """Classify an application question deterministically."""
    normalized = _norm(raw_question)
    options = available_options or []

    # Check known question concepts
    for concept_key, concept in QUESTION_CONCEPTS.items():
        for alias in concept["aliases"]:
            if _norm(alias) == normalized or _semantic_match(normalized, _norm(alias)):
                return QuestionClassification(
                    raw_question=raw_question,
                    normalized=normalized,
                    category=concept["category"],
                    sensitivity=concept["sensitivity"],
                    is_known_concept=True,
                    concept_key=concept_key,
                    answer_type=_detect_answer_type(options),
                    available_options=options,
                )

    # Classify by content
    category = _classify_by_content(normalized)
    sensitivity = _classify_sensitivity(normalized)

    return QuestionClassification(
        raw_question=raw_question,
        normalized=normalized,
        category=category,
        sensitivity=sensitivity,
        is_known_concept=False,
        answer_type=_detect_answer_type(options),
        available_options=options,
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

    # Check memory for verified answer
    verified_answer = memory.get_verified_answer(question)
    if verified_answer:
        return QuestionHandlingResult(
            classification=classification,
            answer=verified_answer.answer,
            source=verified_answer.source,
            verification_status=verified_answer.verification_status,
            needs_user_input=False,
            is_blocked=False,
        )

    # Check memory for any answer (not just verified)
    any_answer = memory.get_answer(question)
    if any_answer and classification.sensitivity == "LOW":
        return QuestionHandlingResult(
            classification=classification,
            answer=any_answer.answer,
            source=any_answer.source,
            verification_status=any_answer.verification_status,
            needs_user_input=False,
            is_blocked=False,
            warning="Using unverified answer for low-sensitivity field.",
        )

    # High sensitivity without verified answer -> must ask user
    if classification.sensitivity == "HIGH":
        return QuestionHandlingResult(
            classification=classification,
            answer=None,
            needs_user_input=True,
            is_blocked=False,
            warning="Sensitive question requires explicit user verification.",
        )

    # Unknown question -> ask user
    return QuestionHandlingResult(
        classification=classification,
        answer=None,
        needs_user_input=True,
        is_blocked=False,
    )


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


def _classify_by_content(question: str) -> str:
    """Classify question category by content analysis."""
    from app.application_execution.memory import (
        QUESTION_CATEGORY_AVAILABILITY,
        QUESTION_CATEGORY_EXPERIENCE,
        QUESTION_CATEGORY_MOTIVATION,
        QUESTION_CATEGORY_PERSONAL,
        QUESTION_CATEGORY_SALARY,
        QUESTION_CATEGORY_TECHNICAL,
    )

    q = question.lower()

    # Authorization
    if any(kw in q for kw in ["authorized", "authorization", "sponsorship", "visa", "legal"]):
        return QUESTION_CATEGORY_AUTHORIZATION

    # Salary
    if any(kw in q for kw in ["salary", "compensation", "ctc", "pay", "wage", "package"]):
        return QUESTION_CATEGORY_SALARY

    # Experience
    if any(kw in q for kw in ["experience", "years", "background", "history", "worked"]):
        return QUESTION_CATEGORY_EXPERIENCE

    # Availability
    if any(kw in q for kw in ["available", "availability", "start", "join", "notice"]):
        return QUESTION_CATEGORY_AVAILABILITY

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
    return overlap / max(len(t1), len(t2)) >= 0.6
