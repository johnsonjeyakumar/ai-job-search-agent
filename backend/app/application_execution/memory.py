"""Application memory for reusable verified answers (Phase 12).

Stores verified answers to application questions for reuse across submissions.
Answers are categorized by verification status and sensitivity level.
Only USER_VERIFIED or SYSTEM_DERIVED answers may be reused automatically.
EXPIRED, REVOKED, and UNVERIFIED answers are never reused by automatic
application handling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_SPLIT_RE = re.compile(r"\W+")


def _norm(text: str | None) -> str:
    return _SPLIT_RE.sub(" ", (text or "").lower()).strip()


def _tokens(text: str | None) -> set[str]:
    return set(_norm(text).split())


# ---------------------------------------------------------------------------
# Verification statuses
# ---------------------------------------------------------------------------
VERIFICATION_UNVERIFIED = "UNVERIFIED"
VERIFICATION_USER_VERIFIED = "USER_VERIFIED"
VERIFICATION_SYSTEM_DERIVED = "SYSTEM_DERIVED"
VERIFICATION_EXPIRED = "EXPIRED"

# ---------------------------------------------------------------------------
# Answer types
# ---------------------------------------------------------------------------
ANSWER_TYPE_TEXT = "TEXT"
ANSWER_TYPE_SELECT = "SELECT"
ANSWER_TYPE_BOOLEAN = "BOOLEAN"
ANSWER_TYPE_FILE = "FILE"

# ---------------------------------------------------------------------------
# Question categories (deterministic)
# ---------------------------------------------------------------------------
QUESTION_CATEGORY_AUTHORIZATION = "AUTHORIZATION"
QUESTION_CATEGORY_SALARY = "SALARY"
QUESTION_CATEGORY_EXPERIENCE = "EXPERIENCE"
QUESTION_CATEGORY_AVAILABILITY = "AVAILABILITY"
QUESTION_CATEGORY_MOTIVATION = "MOTIVATION"
QUESTION_CATEGORY_PERSONAL = "PERSONAL"
QUESTION_CATEGORY_TECHNICAL = "TECHNICAL"
QUESTION_CATEGORY_UNKNOWN = "UNKNOWN"
QUESTION_CATEGORY_KNOCKOUT = "KNOCKOUT"
QUESTION_CATEGORY_WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
QUESTION_CATEGORY_SPONSORSHIP = "SPONSORSHIP"
QUESTION_CATEGORY_RELOCATION = "RELOCATION"
QUESTION_CATEGORY_COMPENSATION = "COMPENSATION"
QUESTION_CATEGORY_SENSITIVE = "SENSITIVE"
QUESTION_CATEGORY_DEMOGRAPHIC = "DEMOGRAPHIC"
QUESTION_CATEGORY_LEGAL_DECLARATION = "LEGAL_DECLARATION"
QUESTION_CATEGORY_ATTESTATION = "ATTESTATION"
QUESTION_CATEGORY_CONSENT = "CONSENT"
QUESTION_CATEGORY_E_SIGNATURE = "E_SIGNATURE"
QUESTION_CATEGORY_AMBIGUOUS = "AMBIGUOUS"

# Sensitive question keywords
_SENSITIVE_KEYWORDS = {
    "authorized", "authorization", "sponsorship", "visa", "legal",
    "disability", "criminal", "convicted", "felony", "misdemeanor",
    "gender", "race", "ethnicity", "religion", "age", "marital",
    "pregnant", "military", "veteran",
    "date of birth", "dob", "social security", "ssn", "national id",
    "background check", "drug test", "medical", "health condition",
    "genetic information", "citizenship", "immigration status",
}

# Demographic keywords (must never be inferred)
_DEMOGRAPHIC_KEYWORDS = {
    "gender", "race", "ethnicity", "religion", "disability",
    "veteran", "military", "sexual orientation", "marital status",
    "national origin", "color", "age", "pregnancy",
    "genetic information", "citizenship",
}

# Declaration/attestation keywords
_DECLARATION_KEYWORDS = {
    "certify", "confirm", "attest", "declare", "acknowledge",
    "understand", "agree to the terms", "true and accurate",
    "information provided is accurate", "information above is true",
    "electronic signature", "signature",
}


@dataclass
class VerifiedAnswer:
    """A verified answer to an application question."""

    id: int | None = None
    normalized_question: str = ""
    raw_question: str = ""
    answer: str = ""
    answer_type: str = ANSWER_TYPE_TEXT
    source: str = VERIFICATION_USER_VERIFIED
    verification_status: str = VERIFICATION_UNVERIFIED
    sensitivity: str = "LOW"
    question_category: str = QUESTION_CATEGORY_UNKNOWN
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    use_count: int = 0
    evidence: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "normalized_question": self.normalized_question,
            "raw_question": self.raw_question,
            "answer": self.answer,
            "answer_type": self.answer_type,
            "source": self.source,
            "verification_status": self.verification_status,
            "sensitivity": self.sensitivity,
            "question_category": self.question_category,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "use_count": self.use_count,
            "evidence": self.evidence,
            "tags": self.tags,
        }


@dataclass
class UnknownQuestion:
    """An unknown application question that needs user input."""

    id: int | None = None
    raw_question: str = ""
    page_url: str | None = None
    field_type: str = "text"
    available_options: list[str] = field(default_factory=list)
    detected_context: str = ""
    suggested_answer: str | None = None
    resolved: bool = False
    created_at: datetime | None = None


@dataclass
class MemoryStore:
    """In-memory store for verified answers.

    In production, this would be backed by a database. For now, it's an
    in-memory implementation that can be easily swapped.
    """

    answers: dict[str, VerifiedAnswer] = field(default_factory=dict)
    unknown_questions: dict[str, UnknownQuestion] = field(default_factory=dict)
    user_field_mappings: dict[str, str] = field(default_factory=dict)

    def add_answer(
        self,
        question: str,
        answer: str,
        source: str = VERIFICATION_USER_VERIFIED,
        answer_type: str = ANSWER_TYPE_TEXT,
        evidence: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> VerifiedAnswer:
        """Add or update a verified answer."""
        normalized = _norm(question)
        now = datetime.now(timezone.utc)

        if normalized in self.answers:
            existing = self.answers[normalized]
            existing.answer = answer
            existing.source = source
            existing.verification_status = source
            existing.answer_type = answer_type
            existing.updated_at = now
            if evidence:
                existing.evidence = evidence
            if tags:
                existing.tags = tags
            return existing

        sensitivity = _classify_sensitivity(normalized)
        category = _classify_question_category(normalized)

        verified = VerifiedAnswer(
            normalized_question=normalized,
            raw_question=question,
            answer=answer,
            answer_type=answer_type,
            source=source,
            verification_status=source,
            sensitivity=sensitivity,
            question_category=category,
            created_at=now,
            updated_at=now,
            evidence=evidence or [],
            tags=tags or [],
        )
        self.answers[normalized] = verified
        return verified

    def get_answer(self, question: str) -> VerifiedAnswer | None:
        """Get a reusable answer for a question.

        Returns None for EXPIRED, REVOKED, or UNVERIFIED answers —
        these are never reused by automatic application handling.
        Only USER_VERIFIED and SYSTEM_DERIVED answers are returned.
        """
        normalized = _norm(question)
        answer = self.answers.get(normalized)
        if answer is None:
            return None
        # Block revoked/expired/unverified from automatic reuse
        if answer.verification_status in (
            VERIFICATION_EXPIRED,
            VERIFICATION_UNVERIFIED,
        ):
            return None
        answer.last_used_at = datetime.now(timezone.utc)
        answer.use_count += 1
        return answer

    def get_verified_answer(self, question: str) -> VerifiedAnswer | None:
        """Get only USER_VERIFIED answers (safe for sensitive fields)."""
        answer = self.get_answer(question)
        if answer and answer.verification_status == VERIFICATION_USER_VERIFIED:
            return answer
        return None

    def revoke_answer(self, question: str) -> bool:
        """Revoke a verified answer."""
        normalized = _norm(question)
        if normalized in self.answers:
            self.answers[normalized].verification_status = VERIFICATION_EXPIRED
            return True
        return False

    def verify_answer(self, question: str) -> bool:
        """Mark an answer as user-verified."""
        normalized = _norm(question)
        if normalized in self.answers:
            self.answers[normalized].verification_status = VERIFICATION_USER_VERIFIED
            self.answers[normalized].source = VERIFICATION_USER_VERIFIED
            return True
        return False

    def list_answers(
        self,
        category: str | None = None,
        sensitivity: str | None = None,
        verification: str | None = None,
    ) -> list[VerifiedAnswer]:
        """List answers with optional filters."""
        results = list(self.answers.values())
        if category:
            results = [a for a in results if a.question_category == category]
        if sensitivity:
            results = [a for a in results if a.sensitivity == sensitivity]
        if verification:
            results = [a for a in results if a.verification_status == verification]
        return results

    def add_unknown_question(
        self,
        question: str,
        page_url: str | None = None,
        field_type: str = "text",
        options: list[str] | None = None,
        context: str = "",
    ) -> UnknownQuestion:
        """Record an unknown question for user resolution."""
        normalized = _norm(question)
        now = datetime.now(timezone.utc)

        # Check if we have a suggested answer from memory
        suggested = None
        for answer in self.answers.values():
            if _semantic_match(normalized, answer.normalized_question):
                suggested = answer.answer
                break

        unknown = UnknownQuestion(
            raw_question=question,
            page_url=page_url,
            field_type=field_type,
            available_options=options or [],
            detected_context=context,
            suggested_answer=suggested,
            created_at=now,
        )
        self.unknown_questions[normalized] = unknown
        return unknown

    def resolve_unknown(
        self, question: str, answer: str, verified: bool = True
    ) -> VerifiedAnswer:
        """Resolve an unknown question with a user-provided answer."""
        normalized = _norm(question)
        if normalized in self.unknown_questions:
            self.unknown_questions[normalized].resolved = True

        source = VERIFICATION_USER_VERIFIED if verified else VERIFICATION_UNVERIFIED
        return self.add_answer(question, answer, source=source)

    def add_field_mapping(self, raw_label: str, canonical: str) -> None:
        """Store a user-verified field mapping."""
        self.user_field_mappings[_norm(raw_label)] = canonical

    def get_field_mapping(self, raw_label: str) -> str | None:
        """Get a user-verified field mapping."""
        return self.user_field_mappings.get(_norm(raw_label))


def _classify_sensitivity(question: str) -> str:
    """Classify question sensitivity based on content."""
    question_lower = question.lower()
    for keyword in _SENSITIVE_KEYWORDS:
        if keyword in question_lower:
            return "HIGH"
    # Medium sensitivity for salary/compensation questions
    salary_keywords = {"salary", "compensation", "ctc", "pay", "wage", "package"}
    if any(kw in question_lower for kw in salary_keywords):
        return "MEDIUM"
    return "LOW"


def _classify_question_category(question: str) -> str:
    """Classify question into a category."""
    question_lower = question.lower()

    # Authorization
    auth_keywords = {"authorized", "authorization", "sponsorship", "visa", "legal"}
    if any(kw in question_lower for kw in auth_keywords):
        return QUESTION_CATEGORY_AUTHORIZATION

    # Salary
    salary_keywords = {"salary", "compensation", "ctc", "pay", "wage", "package"}
    if any(kw in question_lower for kw in salary_keywords):
        return QUESTION_CATEGORY_SALARY

    # Experience
    exp_keywords = {"experience", "years", "background", "history", "worked"}
    if any(kw in question_lower for kw in exp_keywords):
        return QUESTION_CATEGORY_EXPERIENCE

    # Availability
    avail_keywords = {"available", "availability", "start", "join", "notice"}
    if any(kw in question_lower for kw in avail_keywords):
        return QUESTION_CATEGORY_AVAILABILITY

    # Motivation
    motiv_keywords = {"why", "motivation", "interested", "want", "reason"}
    if any(kw in question_lower for kw in motiv_keywords):
        return QUESTION_CATEGORY_MOTIVATION

    # Personal
    personal_keywords = {"name", "email", "phone", "address", "location", "city"}
    if any(kw in question_lower for kw in personal_keywords):
        return QUESTION_CATEGORY_PERSONAL

    # Technical
    tech_keywords = {"skill", "technology", "programming", "language", "framework"}
    if any(kw in question_lower for kw in tech_keywords):
        return QUESTION_CATEGORY_TECHNICAL

    return QUESTION_CATEGORY_UNKNOWN


def _semantic_match(q1: str, q2: str) -> bool:
    """Check if two questions are semantically similar."""
    t1 = _tokens(q1)
    t2 = _tokens(q2)
    if not t1 or not t2:
        return False
    overlap = len(t1 & t2)
    return overlap / max(len(t1), len(t2)) >= 0.6
