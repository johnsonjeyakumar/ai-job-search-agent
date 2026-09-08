"""Evidence-bound answer generation engine (Phase 12).

Generates application answers by matching questions to verified profile data
and memory. Answers are always evidence-bound — AI may only provide wording,
never invent facts. Sensitive answers require explicit verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.application_execution.memory import (
    MemoryStore,
    _tokens,
)
from app.application_execution.question_handler import (
    QuestionClassification,
    classify_question,
)

# ---------------------------------------------------------------------------
# Evidence levels
# ---------------------------------------------------------------------------
EVIDENCE_EXACT = "EXACT"          # Direct profile field match
EVIDENCE_DERIVED = "DERIVED"      # Computed from profile data
EVIDENCE_AI_WORDING = "AI_WORDING" # AI provides wording for verified facts
EVIDENCE_UNVERIFIED = "UNVERIFIED" # No evidence found


@dataclass
class GeneratedAnswer:
    """An answer generated from evidence."""

    answer: str
    evidence_level: str = EVIDENCE_UNVERIFIED
    evidence_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    needs_review: bool = False
    review_reason: str | None = None
    can_auto_fill: bool = False


@dataclass
class AnswerGenerationResult:
    """Result of answer generation for a question."""

    question: str
    classification: QuestionClassification
    generated_answer: GeneratedAnswer | None = None
    needs_user_input: bool = False
    is_blocked: bool = False
    block_reason: str | None = None


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
# Job context matching
# ---------------------------------------------------------------------------

def _match_by_job_context(
    question: str,
    profile: ProfileDataProvider,
    job_context: dict,
) -> tuple[str | None, str, list[str]]:
    """Match question to profile evidence using job context as a bridge.

    The job context describes what the role requires. The profile provides
    evidence of what the candidate has. The overlap between the two
    produces evidence-bound, job-specific answers.

    Returns (value, evidence_level, sources). None if no evidence found.
    """
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
# Answer generation
# ---------------------------------------------------------------------------

def generate_answer(
    question: str,
    memory: MemoryStore,
    profile: ProfileDataProvider,
    job_context: dict | None = None,
) -> AnswerGenerationResult:
    """Generate an answer for an application question.

    Decision flow:
    1. Classify the question
    2. Check memory for verified answer
    3. Try to match profile data (evidence-bound)
    4. Generate wording if evidence exists (AI may only rephrase)
    5. Apply sensitivity policy
    6. Return result
    """
    classification = classify_question(question)

    # Step 1: Check memory for verified answer
    verified = memory.get_verified_answer(question)
    if verified:
        return AnswerGenerationResult(
            question=question,
            classification=classification,
            generated_answer=GeneratedAnswer(
                answer=verified.answer,
                evidence_level=EVIDENCE_EXACT,
                evidence_sources=[f"memory.{verified.normalized_question}"],
                confidence=1.0,
                needs_review=False,
                can_auto_fill=classification.sensitivity != "HIGH",
            ),
        )

    # Step 2: Check memory for any answer
    any_answer = memory.get_answer(question)
    if any_answer and classification.sensitivity == "LOW":
        return AnswerGenerationResult(
            question=question,
            classification=classification,
            generated_answer=GeneratedAnswer(
                answer=any_answer.answer,
                evidence_level=EVIDENCE_DERIVED,
                evidence_sources=[f"memory.{any_answer.normalized_question}"],
                confidence=0.8,
                needs_review=True,
                review_reason="Using unverified answer for low-sensitivity field.",
                can_auto_fill=True,
            ),
        )

    # Step 3: Try canonical field match
    from app.application_execution.base import DetectedField
    from app.application_execution.semantic_mapper import map_field_semantic

    detected = DetectedField(label=question, kind="text")
    mapping = map_field_semantic(detected)

    if mapping.canonical:
        value, evidence_level = _match_profile_field(mapping.canonical, profile)
        if value:
            return AnswerGenerationResult(
                question=question,
                classification=classification,
                generated_answer=GeneratedAnswer(
                    answer=value,
                    evidence_level=evidence_level,
                    evidence_sources=[f"profile.{mapping.canonical}"],
                    confidence=0.9,
                    needs_review=classification.sensitivity == "MEDIUM",
                    review_reason="Profile match for medium-sensitivity field.",
                    can_auto_fill=classification.sensitivity == "LOW",
                ),
            )

    # Step 4: Try content-based match
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
                needs_review=True,
                review_reason="Content-based match requires verification.",
                can_auto_fill=False,
            ),
        )

    # Step 5: Try job-context-based match for motivation questions
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
                    needs_review=True,
                    review_reason="Job-context match requires verification.",
                    can_auto_fill=False,
                ),
            )

    # Step 6: No evidence found
    return AnswerGenerationResult(
        question=question,
        classification=classification,
        generated_answer=None,
        needs_user_input=True,
        is_blocked=False,
    )
