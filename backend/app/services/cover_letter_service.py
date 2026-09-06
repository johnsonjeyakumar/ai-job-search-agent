"""Cover letter generation for application packages (Phase 6).

Cover letters are optional. Deterministic output is a template assembled
only from real stored facts; AI output is validated against ``AICoverLetter``
and rejected (skipped) unless it is clean. A letter is never fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.services.application_truthfulness import asserts_new_fact

STATUS_SKIPPED = "skipped"
STATUS_GENERATED = "generated"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_ERROR = "error"

_HEADERS = (
    "Dear Hiring Team,",
    "",
)


@dataclass
class CoverLetterResult:
    text: str | None
    status: str = STATUS_SKIPPED
    feedback: str = ""


async def generate_cover_letter_for_package(
    db,
    job: Job,
    profile: Profile | None,
    resume: Resume | None,
    evidence_entries: list,
    requested: bool = False,
) -> CoverLetterResult:
    """Generate a cover letter.

    With the mock provider (or without ``requested``) no letter is produced
    (status ``skipped``). With a real provider the AI draft is validated; a
    clean draft is kept, a draft that asserts new facts is downgraded to
    ``needs_review``.
    """
    if not requested:
        return CoverLetterResult(text=None, status=STATUS_SKIPPED)

    deterministic = _deterministic_letter(job, profile, resume)

    from app.ai.registry import get_provider

    provider = get_provider()
    if provider.name == "mock":
        return CoverLetterResult(
            text=deterministic,
            status=STATUS_GENERATED,
            feedback="Deterministic template from stored facts (mock AI).",
        )

    from pydantic import ValidationError

    from app.schemas.ai_application import AICoverLetter

    payload = await provider.draft_cover_letter(job, profile, resume)
    if payload is None:
        return CoverLetterResult(
            text=deterministic,
            status=STATUS_GENERATED,
            feedback="AI provider had nothing to contribute; used deterministic template.",
        )
    try:
        letter = AICoverLetter.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return CoverLetterResult(
            text=deterministic,
            status=STATUS_GENERATED,
            feedback="AI cover letter failed validation; used deterministic template.",
        )
    supported = {norm_n(e.evidence) for e in evidence_entries if e.evidence}
    if asserts_new_fact(letter.text, profile, resume, supported) or not letter.text.strip():
        return CoverLetterResult(
            text=letter.text,
            status=STATUS_NEEDS_REVIEW,
            feedback="AI draft asserts facts not backed by stored data; review before use.",
        )
    return CoverLetterResult(
        text=letter.text,
        status=STATUS_GENERATED,
        feedback="AI-drafted cover letter validated against stored facts.",
    )


def _deterministic_letter(
    job: Job, profile: Profile | None, resume: Resume | None
) -> str | None:
    if profile is None:
        return None
    skills = ", ".join(
        sorted(
            {
                s
                for attr in (
                    "skills",
                    "skills_programming",
                    "skills_frameworks",
                    "skills_databases",
                    "skills_tools",
                    "skills_other",
                )
                for s in (getattr(profile, attr) or [])
            }
        )
    )
    name = profile.name or (resume.name if resume is not None else "the candidate")
    lines = list(_HEADERS)
    lines.append(f"I am writing to express my interest in the {job.title} role at {job.company}.")
    if skills:
        lines.append(
            f"My background includes experience with {skills}, which aligns with the role."
        )
    degree = profile.degree
    if degree:
        univ = f" from {profile.university}" if profile.university else ""
        lines.append(f"I hold a {degree}{univ}.")
    if profile.projects:
        proj = profile.projects[0]
        lines.append(
            f"In a recent project, '{proj.get('name')}', I worked on "
            f"{', '.join(proj.get('technologies') or []) or 'relevant technologies'}."
        )
    lines.append("I am happy to discuss how I can contribute to the team.")
    lines.append("")
    lines.append("Best regards,")
    lines.append(name)
    return "\n".join(lines)


def norm_n(value: str) -> str:
    from app.services import skill_normalizer as norm

    return norm.normalize(value)
