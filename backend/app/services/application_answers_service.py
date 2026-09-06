"""Application question bank and answers (Phase 6).

Answers are built exclusively from real profile/preferences/resume evidence.
When data is missing the answer is left open (NEEDS_REVIEW) rather than
invented. AI may draft answers, but every AI answer is validated against
``AIApplicationAnswer`` (``extra="forbid"``) and re-checked for fabricated
facts before it can be stored.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import skill_normalizer as norm
from app.services.application_truthfulness import (
    asserts_new_fact,
    known_locations,
    known_skills,
)

VALID = "VALID"
NEEDS_REVIEW = "NEEDS_REVIEW"
INVALID = "INVALID"

# Categories sourced straight from the profile. Missing data -> NEEDS_REVIEW.
_CUSTOM_FIELDS = (
    "notice_period",
    "work_authorization",
)

# Required categories for a ready package (all questions must be answered).
REQUIRED_CATEGORIES = (
    "motivation",
    "experience",
    "technical skills",
    "project",
    "education",
    "relocation",
    "remote",
    "salary",
    "notice period",
    "work authorization",
    "availability",
)


@dataclass
class AnswerDraft:
    category: str
    question: str
    answer: str | None
    source_evidence: list[str] = field(default_factory=list)
    confidence: str = "LOW"
    validation_status: str = NEEDS_REVIEW
    feedback: str = ""
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "question": self.question,
            "answer": self.answer,
            "source_evidence": self.source_evidence,
            "confidence": self.confidence,
            "validation_status": self.validation_status,
            "feedback": self.feedback,
            "required": self.required,
        }


def _question_bank(
    job: Job, profile: Profile | None, preferences: Preferences | None
) -> list[dict[str, str]]:
    return [
        {"category": c, "question": q}
        for c, q in [
            ("motivation", f"Why do you want to join {job.company} as {job.title}?"),
            ("experience", "Summarize your relevant professional experience."),
            ("technical skills", "Which technical skills do you bring to this role?"),
            ("project", "Describe a project you have worked on."),
            ("education", "What is your educational background?"),
            ("relocation", "Are you willing to relocate for this role?"),
            ("remote", "What is your work-mode preference?"),
            ("salary", "What are your salary expectations?"),
            ("notice period", "What is your notice period?"),
            ("work authorization", "Are you authorized to work?"),
            ("availability", "When can you start?"),
        ]
    ]


def draft_answers(
    db,
    job: Job,
    profile: Profile | None,
    preferences: Preferences | None,
    resume: Resume | None,
    target_role: str | None,
) -> list[AnswerDraft]:
    """Deterministic answers, optionally enriched by validated AI drafts."""
    answers = [
        _draft(q, job, profile, preferences, resume, target_role)
        for q in _question_bank(job, profile, preferences)
    ]
    return answers


async def refine_answers_with_ai(
    job: Job,
    profile: Profile | None,
    resume: Resume | None,
    drafts: list[AnswerDraft],
) -> list[AnswerDraft]:
    """Merge validated AI drafts over the deterministic answers."""
    from pydantic import ValidationError

    from app.ai.registry import get_provider
    from app.schemas.ai_application import AIApplicationAnswer

    provider = get_provider()
    if provider.name == "mock":
        return drafts
    questions = [{"category": d.category, "question": d.question} for d in drafts]
    payload = await provider.draft_application_answers(job, profile, resume, questions)
    if not payload:
        return drafts
    parsed = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(AIApplicationAnswer.model_validate(item))
        except (ValidationError, TypeError, ValueError):
            continue
    by_question = {norm.normalize(d.question): d for d in drafts}
    for ai in parsed:
        target = by_question.get(norm.normalize(ai.question))
        if target is None:
            continue
        ai_supported = set(ai.source_evidence)
        new_fact = asserts_new_fact(ai.answer, profile, resume, ai_supported)
        if new_fact or not ai.answer:
            target.validation_status = INVALID
            target.feedback = (
                "AI draft introduces facts not supported by stored data."
                if ai.answer
                else "AI draft came back empty."
            )
            continue
        target.answer = ai.answer
        target.source_evidence = list(ai.source_evidence) or target.source_evidence
        target.confidence = _map_confidence(ai.confidence)
        target.validation_status = VALID
        target.feedback = "AI-drafted answer validated."
    return drafts


def _draft(
    question: dict[str, str],
    job: Job,
    profile: Profile | None,
    preferences: Preferences | None,
    resume: Resume | None,
    target_role: str | None,
) -> AnswerDraft:
    category = question["category"]
    text = question["question"]
    if category == "motivation":
        return _motivation(text, job, profile, target_role)
    if category == "experience":
        return _experience(text, profile)
    if category == "technical skills":
        return _skills(text, job, profile, resume)
    if category == "project":
        return _project(text, job, profile)
    if category == "education":
        return _education(text, profile)
    if category == "relocation":
        return _relocation(text, job, profile, preferences)
    if category == "remote":
        return _remote(text, profile, preferences)
    if category == "salary":
        return _salary(text, profile, preferences)
    if category == "notice period":
        value = profile.notice_period if profile is not None else None
        return _custom_field("notice period", text, value)
    if category == "work authorization":
        value = profile.work_authorization if profile is not None else None
        return _custom_field("work authorization", text, value)
    if category == "availability":
        value = profile.notice_period if profile is not None else None
        if value:
            return AnswerDraft(
                category="availability",
                question=text,
                answer=f"I can join after my notice period ({value}).",
                source_evidence=[f"Profile.notice_period: {value}"],
                confidence="HIGH",
                validation_status=VALID,
                feedback="From profile notice period.",
            )
        return AnswerDraft(
            category="availability",
            question=text,
            answer=None,
            confidence="LOW",
            validation_status=NEEDS_REVIEW,
            feedback="Notice period is not stored on the profile.",
        )
    return AnswerDraft(category=category, question=text, validation_status=NEEDS_REVIEW)


def _motivation(text, job, profile, target_role) -> AnswerDraft:
    role_source = target_role or (
        profile.preferred_roles[0]
        if profile is not None and profile.preferred_roles
        else None
    )
    if not role_source:
        return AnswerDraft(
            category="motivation", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="No target role on file; the answer needs user input.",
        )
    answer = (
        f"I am applying for {target_role or 'this'} role at {job.company} "
        f"({job.title}). The position matches my target role and background."
    )
    return AnswerDraft(
        category="motivation", question=text, answer=answer,
        source_evidence=[f"Profile.preferred_roles: {role_source}"],
        confidence="HIGH", validation_status=VALID,
        feedback="Derived from target role and job title.",
    )


def _experience(text, profile) -> AnswerDraft:
    if profile is None:
        return AnswerDraft(
            category="experience", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="No profile on file.",
        )
    bits: list[str] = []
    sources: list[str] = []
    if profile.experience_level:
        bits.append(f"{profile.experience_level} experience")
        sources.append(f"Profile.experience_level: {profile.experience_level}")
    intern_lines = []
    for internship in profile.internships or []:
        company = internship.get("company") or ""
        role = internship.get("role") or "internship"
        period = internship.get("period") or internship.get("duration") or ""
        line = f"{role} at {company}" + (f" ({period})" if period else "")
        intern_lines.append(line)
        sources.append(f"Profile.internships: {line}")
    if intern_lines:
        bits.append("; ".join(intern_lines))
    if not bits:
        return AnswerDraft(
            category="experience", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="Experience details are not stored on the profile.",
        )
    answer = " ".join(bits) + "."
    return AnswerDraft(
        category="experience", question=text, answer=answer,
        source_evidence=sources,
        confidence="MEDIUM" if intern_lines else "LOW",
        validation_status=VALID,
        feedback="Built from stored experience and internships.",
    )


def _skills(text, job, profile, resume) -> AnswerDraft:
    known = known_skills(profile, resume)
    if not known:
        return AnswerDraft(
            category="technical skills", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="No skills stored on the profile or resume.",
        )
    from app.services import requirement_extractor as rex

    bundle = rex.extract_job_requirements(job)
    job_terms = {r.canonical for r in bundle.skills if r.canonical}
    matched = sorted(known & job_terms)
    others = sorted(known - job_terms)
    parts: list[str] = []
    if matched:
        parts.append("I bring the requested skills: " + ", ".join(sorted(matched)) + ".")
    if others:
        parts.append("Additional skills include " + ", ".join(others) + ".")
    answer = " ".join(parts)
    return AnswerDraft(
        category="technical skills", question=text, answer=answer,
        source_evidence=[f"Profile/resume skills: {', '.join(sorted(known))}"],
        confidence="HIGH" if matched else "MEDIUM",
        validation_status=VALID,
        feedback="From stored profile/resume skills.",
    )


def _project(text, job, profile) -> AnswerDraft:
    if profile is None or not profile.projects:
        return AnswerDraft(
            category="project", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="No projects stored on the profile.",
        )
    from app.services import requirement_extractor as rex

    bundle = rex.extract_job_requirements(job)
    job_terms = {r.canonical for r in bundle.skills if r.canonical}
    best = profile.projects[0]
    best_hits = 0
    for project in profile.projects:
        tech = {norm.canonicalize(t) for t in (project.get("technologies") or [])}
        hits = len(tech & job_terms)
        if hits > best_hits:
            best, best_hits = project, hits
    name = best.get("name") or "a project"
    tech = best.get("technologies") or []
    desc = best.get("description") or best.get("summary") or ""
    answer = f"Built {name}" + (f" ({', '.join(tech)})" if tech else "")
    if desc:
        answer += f": {desc[:400]}"
    return AnswerDraft(
        category="project", question=text, answer=answer,
        source_evidence=[
            f"Profile.projects: {name}",
            *[f"Project.technologies: {t}" for t in tech],
        ],
        confidence="MEDIUM" if best_hits else "LOW",
        validation_status=VALID,
        feedback="From stored project records.",
    )


def _education(text, profile) -> AnswerDraft:
    if profile is None or not profile.degree:
        return AnswerDraft(
            category="education", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="Education is not stored on the profile.",
        )
    parts = [profile.degree]
    if profile.university:
        parts.append(profile.university)
    if profile.graduation_year:
        parts.append(str(profile.graduation_year))
    answer = f"{' at '.join(parts)}."
    return AnswerDraft(
        category="education", question=text, answer=answer,
        source_evidence=[f"Profile.degree: {profile.degree}"],
        confidence="HIGH", validation_status=VALID,
        feedback="From stored profile education.",
    )


def _relocation(text, job, profile, preferences) -> AnswerDraft:
    places = known_locations(profile, preferences)
    job_place = " ".join([p for p in [job.location or "", job.remote_type or ""] if p])
    if not places:
        return AnswerDraft(
            category="relocation", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="Preferred locations are not stored on the profile/preferences.",
        )
    if any(_place_in_job(pref, job_place) for pref in places):
        verdict = "I am available for this location."
    elif "remote" in job_place.lower() and any("remote" in p for p in places):
        verdict = "I am comfortable with remote work."
    else:
        verdict = "I am open to relocating for the right role."
    answer = f"Based in {', '.join(sorted(places))}. " + verdict
    return AnswerDraft(
        category="relocation", question=text, answer=answer,
        source_evidence=[f"Profile/preferences locations: {', '.join(sorted(places))}"],
        confidence="MEDIUM", validation_status=VALID,
        feedback="From stored location preferences.",
    )


def _place_in_job(pref: str, job_place: str) -> bool:
    import re

    key = norm.normalize(pref)
    pattern = rf"(?<![a-z0-9+.#]){re.escape(key)}s?(?![a-z0-9+.#])"
    return bool(re.search(pattern, norm.normalize(job_place)))


def _remote(text, profile, preferences) -> AnswerDraft:
    mode = None
    if profile is not None and profile.remote_preference:
        mode = profile.remote_preference
    elif preferences is not None and preferences.remote_types:
        mode = "/".join(preferences.remote_types)
    if not mode:
        return AnswerDraft(
            category="remote", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="Work-mode preference is not stored.",
        )
    answer = f"Preferred work mode: {mode}."
    return AnswerDraft(
        category="remote", question=text, answer=answer,
        source_evidence=[f"Profile.preferences remote: {mode}"],
        confidence="HIGH", validation_status=VALID,
        feedback="From stored remote preference.",
    )


def _salary(text, profile, preferences) -> AnswerDraft:
    src = None
    value = None
    if profile is not None and profile.salary_preference:
        src, value = "Profile.salary_preference", profile.salary_preference
    elif preferences is not None and (
        preferences.salary_min is not None or preferences.salary_max is not None
    ):
        lo = preferences.salary_min or 0
        hi = preferences.salary_max or ""
        src = "Preferences"
        value = f"{lo}-{hi} LPA" if hi else f"min {lo} LPA"
    if not value:
        return AnswerDraft(
            category="salary", question=text, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback="Salary expectation is not stored.",
        )
    answer = f"My expectation is around {value}."
    return AnswerDraft(
        category="salary", question=text, answer=answer,
        source_evidence=[f"{src}: {value}"],
        confidence="HIGH", validation_status=VALID,
        feedback="From stored salary expectation.",
    )


def _custom_field(category: str, question: str, value: str | None) -> AnswerDraft:
    if not value:
        return AnswerDraft(
            category=category, question=question, answer=None,
            confidence="LOW", validation_status=NEEDS_REVIEW,
            feedback=f"{category} is not stored on the profile.",
        )
    answer = value if category == "work authorization" else f"I have a notice period of {value}."
    return AnswerDraft(
        category=category, question=question, answer=answer,
        source_evidence=[f"Profile.{'_'.join(category.split())}: {value}"],
        confidence="HIGH", validation_status=VALID,
        feedback="From stored profile field.",
    )


def _map_confidence(value: float | None) -> str:
    if value is None:
        return "LOW"
    if value >= 0.8:
        return "HIGH"
    if value >= 0.5:
        return "MEDIUM"
    return "LOW"
