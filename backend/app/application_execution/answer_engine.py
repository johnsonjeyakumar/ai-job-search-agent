"""Evidence-bound answer generation engine (Phase 12 + Phase 21).

Generates application answers by matching questions to verified profile data
and memory. Answers are always evidence-bound — AI may only provide wording,
never invent facts. Sensitive answers require explicit verification.

Phase 21 adds:
- Answer source priority (5 levels)
- Confidence states (VERIFIED, DERIVED_VERIFIED, AMBIGUOUS, MISSING, UNSAFE, CONTRADICTORY)
- Contradiction detection between profile sources
- Knockout-aware answer generation
- Declaration/attestation handling
- Electronic signature safety
- Does-not-meet handling
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.application_execution.memory import (
    MemoryStore,
    _tokens,
)
from app.application_execution.question_handler import (
    AnswerConfidence,
    QuestionClass,
    QuestionClassification,
    classify_question,
    compare_experience_requirement,
)

# ---------------------------------------------------------------------------
# Evidence levels (expanded)
# ---------------------------------------------------------------------------
EVIDENCE_EXACT = "EXACT"            # Direct profile field match
EVIDENCE_DERIVED = "DERIVED"        # Computed from profile data
EVIDENCE_AI_WORDING = "AI_WORDING"  # AI provides wording for verified facts
EVIDENCE_UNVERIFIED = "UNVERIFIED"  # No evidence found
EVIDENCE_CONTRADICTORY = "CONTRADICTORY"  # Data sources conflict


@dataclass
class GeneratedAnswer:
    """An answer generated from evidence."""

    answer: str
    evidence_level: str = EVIDENCE_UNVERIFIED
    evidence_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    confidence_state: str = AnswerConfidence.MISSING.value
    needs_review: bool = False
    review_reason: str | None = None
    can_auto_fill: bool = False
    question_class: str = QuestionClass.NORMAL.value
    is_knockout: bool = False
    does_not_meet: bool = False
    contradiction_detail: str | None = None


@dataclass
class AnswerGenerationResult:
    """Result of answer generation for a question."""

    question: str
    classification: QuestionClassification
    generated_answer: GeneratedAnswer | None = None
    needs_user_input: bool = False
    is_blocked: bool = False
    block_reason: str | None = None
    confidence_state: str = AnswerConfidence.MISSING.value


# ---------------------------------------------------------------------------
# Profile data access
# ---------------------------------------------------------------------------

class ProfileDataProvider:
    """Provides access to profile data for evidence binding."""

    def __init__(self, profile: dict | None = None):
        self._profile = profile or {}

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get a profile value by key."""
        value = self._profile.get(key)
        return str(value) if value is not None else default

    def get_numeric(self, key: str) -> float | None:
        """Get a numeric profile value."""
        value = self._profile.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def get_list(self, key: str) -> list[str]:
        """Get a list value from profile."""
        value = self._profile.get(key)
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []

    def has(self, key: str) -> bool:
        """Check if profile has a key."""
        return key in self._profile and self._profile[key] is not None

    def get_all_fields(self) -> dict[str, str | None]:
        """Get all profile fields."""
        return dict(self._profile)


# ---------------------------------------------------------------------------
# Evidence matching
# ---------------------------------------------------------------------------

def _match_profile_field(
    canonical: str,
    profile: ProfileDataProvider,
) -> tuple[str | None, str]:
    """Match a canonical field to profile data. Returns (value, evidence_level)."""
    # Direct profile field mapping
    PROFILE_FIELD_MAP: dict[str, list[str]] = {
        "FIRST_NAME": ["first_name", "firstName"],
        "LAST_NAME": ["last_name", "lastName"],
        "FULL_NAME": ["full_name", "fullName", "name"],
        "EMAIL": ["email"],
        "PHONE": ["phone", "phone_number"],
        "LOCATION": ["location", "city"],
        "STATE": ["state", "province"],
        "COUNTRY": ["country"],
        "ADDRESS": ["address", "street_address"],
        "LINKEDIN_URL": ["linkedin_url", "linkedin"],
        "GITHUB_URL": ["github_url", "github"],
        "PORTFOLIO_URL": ["portfolio_url", "website"],
        "CURRENT_COMPANY": ["company", "current_company"],
        "YEARS_EXPERIENCE": ["years_experience", "experience_years"],
        "CURRENT_ROLE": ["role", "current_role", "title", "current_title"],
        "NOTICE_PERIOD": ["notice_period"],
        "SALARY_EXPECTATION": ["salary_expectation", "expected_salary"],
        "CURRENT_CTC": ["current_ctc", "current_salary"],
        "DEGREE": ["degree", "education"],
        "UNIVERSITY": ["university", "college"],
        "GRADUATION_YEAR": ["graduation_year"],
        "WORK_AUTHORIZATION": ["work_authorization", "authorization"],
        "SPONSORSHIP_REQUIRED": ["sponsorship_required"],
        "RELOCATION": ["relocation", "relocation_willing"],
        "AVAILABILITY": ["availability", "start_date", "available_from"],
    }

    field_keys = PROFILE_FIELD_MAP.get(canonical, [])
    for key in field_keys:
        value = profile.get(key)
        if value:
            return value, EVIDENCE_EXACT

    return None, EVIDENCE_UNVERIFIED


def _match_by_content(
    question: str,
    profile: ProfileDataProvider,
) -> tuple[str | None, str, list[str]]:
    """Match question content to profile data. Returns (value, level, sources)."""
    question_tokens = _tokens(question)
    best_value = None
    best_level = EVIDENCE_UNVERIFIED
    best_sources: list[str] = []

    # Check each profile field for relevance
    for key, value in profile.get_all_fields().items():
        if value is None:
            continue
        key_tokens = _tokens(key)
        # Check if profile key tokens appear in question
        if key_tokens & question_tokens:
            best_value = str(value)
            best_level = EVIDENCE_EXACT
            best_sources.append(f"profile.{key}")

    # Check for common patterns
    patterns = [
        (r"years.*experience", "years_experience"),
        (r"current.*company", "company"),
        (r"notice.*period", "notice_period"),
        (r"salary|compensation|ctc", "salary_expectation"),
    ]
    import re
    for pattern, key in patterns:
        if re.search(pattern, question.lower()):
            value = profile.get(key)
            if value:
                best_value = str(value)
                best_level = EVIDENCE_DERIVED
                best_sources.append(f"pattern.{key}")

    return best_value, best_level, best_sources


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------

def detect_contradiction(
    answers: list[dict],
) -> tuple[bool, str]:
    """Detect contradictions between answer sources.

    Each answer dict should have: value, source, confidence.

    Returns (has_contradiction, detail).
    """
    if len(answers) < 2:
        return False, ""

    # Group by normalized value
    value_groups: dict[str, list[dict]] = {}
    for ans in answers:
        val = str(ans.get("value", "")).strip().lower()
        if val:
            value_groups.setdefault(val, []).append(ans)

    # If all answers are the same, no contradiction
    if len(value_groups) <= 1:
        return False, ""

    # Multiple different values — potential contradiction
    sources = [a.get("source", "unknown") for a in answers]
    values = [a.get("value", "") for a in answers]
    detail = (
        f"Conflicting values from {', '.join(sources)}: "
        f"{', '.join(str(v) for v in values)}"
    )
    return True, detail


# ---------------------------------------------------------------------------
# Job context matching
# ---------------------------------------------------------------------------

def _match_by_job_context(
    question: str,
    profile: ProfileDataProvider,
    job_context: dict,
) -> tuple[str | None, str, list[str]]:
    """Match question to profile evidence using job context as a bridge."""
    job_title = str(job_context.get("title") or "").lower()
    job_description = str(job_context.get("description") or "").lower()
    job_requirements = job_context.get("requirements") or []
    if isinstance(job_requirements, str):
        job_requirements = [r.strip() for r in job_requirements.split(",") if r.strip()]

    # Collect all profile evidence
    profile_skills = (
        profile.get_list("skills")
        + profile.get_list("skills_programming")
        + profile.get_list("skills_frameworks")
    )
    profile_projects = profile.get_list("projects")

    # Tokenize job context
    job_tokens = _tokens(job_description) | _tokens(job_title)
    req_tokens = set()
    for req in job_requirements:
        req_tokens |= _tokens(req)

    # Check if profile skills match job requirements
    skill_overlap = set()
    for skill in profile_skills:
        skill_tokens = _tokens(skill)
        if skill_tokens & (job_tokens | req_tokens):
            skill_overlap.add(skill)

    # Check if profile projects match job context
    project_overlap = set()
    for project in profile_projects:
        project_tokens = _tokens(project)
        if project_tokens & (job_tokens | req_tokens):
            project_overlap.add(project)

    sources: list[str] = []
    evidence_parts: list[str] = []

    if skill_overlap:
        sources.append("profile.skills + job_context")
        evidence_parts.extend(sorted(skill_overlap)[:5])

    if project_overlap:
        sources.append("profile.projects + job_context")
        evidence_parts.extend(sorted(project_overlap)[:3])

    if not sources:
        return None, EVIDENCE_UNVERIFIED, []

    # Generate evidence-bound motivation text
    evidence_text = ", ".join(evidence_parts)
    role_ref = job_title.title() if job_title else "this role"
    answer = (
        f"I am interested in {role_ref} because my experience with "
        f"{evidence_text} aligns well with what the role requires."
    )

    level = EVIDENCE_DERIVED if len(sources) == 1 else EVIDENCE_EXACT
    return answer, level, sources


# ---------------------------------------------------------------------------
# Answer generation (expanded Phase 21)
# ---------------------------------------------------------------------------

def generate_answer(
    question: str,
    memory: MemoryStore,
    profile: ProfileDataProvider,
    job_context: dict | None = None,
    memory_store: MemoryStore | None = None,
) -> AnswerGenerationResult:
    """Generate an answer for an application question.

    Decision flow (5-step priority):
    1. Explicit application-specific verified answer (memory)
    2. Explicit profile value
    3. Verified application memory (unverified but present)
    4. Deterministic derived value from verified structured data
    5. Otherwise -> REVIEW

    LLM-generated text may assist interpretation but MUST NOT override
    verified truth sources.
    """
    classification = classify_question(question)

    # ── Step 1: Check memory for verified answer (highest priority) ────
    verified = memory.get_verified_answer(question)
    if verified:
        # Check for contradiction with profile data
        contradiction, detail = _check_answer_contradiction(
            verified.answer, question, profile, memory,
        )
        if contradiction:
            return AnswerGenerationResult(
                question=question,
                classification=classification,
                generated_answer=GeneratedAnswer(
                    answer=verified.answer,
                    evidence_level=EVIDENCE_CONTRADICTORY,
                    evidence_sources=[f"memory.{verified.normalized_question}"],
                    confidence=0.0,
                    confidence_state=AnswerConfidence.CONTRADICTORY.value,
                    needs_review=True,
                    review_reason=detail,
                    can_auto_fill=False,
                    question_class=classification.question_class,
                    is_knockout=classification.is_knockout,
                    contradiction_detail=detail,
                ),
                needs_user_input=True,
                confidence_state=AnswerConfidence.CONTRADICTORY.value,
            )

        return AnswerGenerationResult(
            question=question,
            classification=classification,
            generated_answer=GeneratedAnswer(
                answer=verified.answer,
                evidence_level=EVIDENCE_EXACT,
                evidence_sources=[f"memory.{verified.normalized_question}"],
                confidence=1.0,
                confidence_state=AnswerConfidence.VERIFIED.value,
                needs_review=False,
                can_auto_fill=classification.sensitivity != "HIGH",
                question_class=classification.question_class,
                is_knockout=classification.is_knockout,
            ),
            confidence_state=AnswerConfidence.VERIFIED.value,
        )

    # ── Step 2: Check profile for canonical field match ────────────────
    from app.application_execution.base import DetectedField
    from app.application_execution.semantic_mapper import map_field_semantic

    detected = DetectedField(label=question, kind="text")
    mapping = map_field_semantic(detected)

    # Skip profile match for signature/declaration/demographic questions
    # These require explicit verified answers, not profile inference
    _SKIP_PROFILE_MATCH = {
        QuestionClass.E_SIGNATURE.value,
        QuestionClass.LEGAL_DECLARATION.value,
        QuestionClass.ATTESTATION.value,
        QuestionClass.DEMOGRAPHIC.value,
    }

    if mapping.canonical and classification.question_class not in _SKIP_PROFILE_MATCH:
        value, evidence_level = _match_profile_field(mapping.canonical, profile)
        if value:
            # Check for knockout experience comparison
            _EXPERIENCE_KNOCKOUT_CLASSES = {
                QuestionClass.EXPERIENCE_REQUIREMENT.value,
                QuestionClass.KNOCKOUT.value,
            }
            if classification.question_class in _EXPERIENCE_KNOCKOUT_CLASSES:
                years = profile.get_numeric("years_experience")
                skills = profile.get_list("skills")
                result, detail = compare_experience_requirement(question, years, skills)
                if result == "DOES_NOT_MEET":
                    return AnswerGenerationResult(
                        question=question,
                        classification=classification,
                        generated_answer=GeneratedAnswer(
                            answer=str(value),
                            evidence_level=EVIDENCE_EXACT,
                            evidence_sources=[f"profile.{mapping.canonical}"],
                            confidence=1.0,
                            confidence_state=AnswerConfidence.VERIFIED.value,
                            needs_review=True,
                            review_reason=detail,
                            can_auto_fill=False,
                            question_class=classification.question_class,
                            is_knockout=True,
                            does_not_meet=True,
                            contradiction_detail=detail,
                        ),
                        needs_user_input=True,
                        confidence_state=AnswerConfidence.VERIFIED.value,
                    )

            return AnswerGenerationResult(
                question=question,
                classification=classification,
                generated_answer=GeneratedAnswer(
                    answer=value,
                    evidence_level=evidence_level,
                    evidence_sources=[f"profile.{mapping.canonical}"],
                    confidence=0.9,
                    confidence_state=AnswerConfidence.DERIVED_VERIFIED.value,
                    needs_review=classification.sensitivity == "MEDIUM",
                    review_reason="Profile match for medium-sensitivity field.",
                    can_auto_fill=classification.sensitivity == "LOW",
                    question_class=classification.question_class,
                    is_knockout=classification.is_knockout,
                ),
                confidence_state=AnswerConfidence.DERIVED_VERIFIED.value,
            )

    # ── Step 3: Try content-based match ────────────────────────────────
    value, level, sources = _match_by_content(question, profile)
    if value:
        return AnswerGenerationResult(
            question=question,
            classification=classification,
            generated_answer=GeneratedAnswer(
                answer=value,
                evidence_level=level,
                evidence_sources=sources,
                confidence=0.7,
                confidence_state=AnswerConfidence.DERIVED_VERIFIED.value,
                needs_review=True,
                review_reason="Content-based match requires verification.",
                can_auto_fill=False,
                question_class=classification.question_class,
                is_knockout=classification.is_knockout,
            ),
            confidence_state=AnswerConfidence.DERIVED_VERIFIED.value,
        )

    # ── Step 4: Try job-context-based match for motivation questions ───
    if job_context and classification.category in ("MOTIVATION", "TECHNICAL"):
        value, level, sources = _match_by_job_context(
            question, profile, job_context
        )
        if value:
            return AnswerGenerationResult(
                question=question,
                classification=classification,
                generated_answer=GeneratedAnswer(
                    answer=value,
                    evidence_level=level,
                    evidence_sources=sources,
                    confidence=0.75,
                    confidence_state=AnswerConfidence.DERIVED_VERIFIED.value,
                    needs_review=True,
                    review_reason="Job-context match requires verification.",
                    can_auto_fill=False,
                    question_class=classification.question_class,
                    is_knockout=classification.is_knockout,
                ),
                confidence_state=AnswerConfidence.DERIVED_VERIFIED.value,
            )

    # ── Step 5: No evidence found → REVIEW ────────────────────────────
    return AnswerGenerationResult(
        question=question,
        classification=classification,
        generated_answer=None,
        needs_user_input=True,
        is_blocked=False,
        confidence_state=AnswerConfidence.MISSING.value,
    )


def _check_answer_contradiction(
    memory_answer: str,
    question: str,
    profile: ProfileDataProvider,
    memory: MemoryStore,
) -> tuple[bool, str]:
    """Check if memory answer contradicts profile data."""
    # Get profile value for same concept
    from app.application_execution.base import DetectedField
    from app.application_execution.semantic_mapper import map_field_semantic

    detected = DetectedField(label=question, kind="text")
    mapping = map_field_semantic(detected)

    if not mapping.canonical:
        return False, ""

    profile_value, _ = _match_profile_field(mapping.canonical, profile)
    if not profile_value:
        return False, ""

    # Normalize and compare
    memory_norm = memory_answer.strip().lower()
    profile_norm = profile_value.strip().lower()

    if memory_norm == profile_norm:
        return False, ""

    # Check for numeric contradiction (years, salary, etc.)
    import re
    memory_nums = re.findall(r"\d+\.?\d*", memory_norm)
    profile_nums = re.findall(r"\d+\.?\d*", profile_norm)

    if memory_nums and profile_nums:
        # If both have numbers but they differ significantly
        try:
            m_val = float(memory_nums[0])
            p_val = float(profile_nums[0])
            if abs(m_val - p_val) > max(m_val, p_val) * 0.3:  # >30% difference
                return True, (
                    f"Memory says {memory_answer}, profile says {profile_value}"
                )
        except ValueError:
            pass

    return False, ""
