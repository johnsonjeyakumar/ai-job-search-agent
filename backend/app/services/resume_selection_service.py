"""Deterministic best-resume selection (Phase 6).

Chooses the resume to base an application package on. The selection is
fully deterministic: it never uses file names, never consults the LLM, and
never fabricates content. Because stored resumes carry metadata only (no
parsed text), scoring uses target-role overlap, job-tech overlap, the active
flag, and recency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import requirement_extractor as rex
from app.services import skill_normalizer as norm


@dataclass
class ResumeCandidate:
    """One resume considered for selection."""

    resume_id: int
    name: str
    target_role: str | None
    version: str | None
    is_active: bool
    score: int
    reasons: list[str] = field(default_factory=list)


@dataclass
class ResumeSelection:
    """Result of deterministic resume selection."""

    selected: ResumeCandidate | None
    score: int | None
    explanation: list[str]
    candidates: list[ResumeCandidate]

    @property
    def selected_id(self) -> int | None:
        return self.selected.resume_id if self.selected is not None else None


def select_resume(
    db,
    job: Job,
    resumes: list[Resume],
    profile: Profile | None,
) -> ResumeSelection:
    """Select the best resume for ``job`` from ``resumes`` (never by filename)."""
    if not resumes:
        return ResumeSelection(
            selected=None,
            score=None,
            explanation=["No resumes on file; the package cannot pick one."],
            candidates=[],
        )

    job_skills = _job_skill_keys(db, job)
    candidates = [_score(resume, job, job_skills) for resume in resumes]
    candidates.sort(
        key=lambda c: (c.score, c.is_active, c.resume_id),
        reverse=True,
    )

    selected = candidates[0]
    explanation = [
        f"Chosen resume: {selected.name} (score {selected.score}/100).",
    ] + [f"  - {r}" for r in selected.reasons]
    if len(candidates) > 1:
        explanation.append(
            "  - Considered "
            + ", ".join(
                f"{c.name} ({c.score}/100)" for c in candidates[1:4]
            )
            + "."
        )
    if selected.score < 40:
        explanation.append(
            "  - Low score: override the selection before preparing."
        )
    return ResumeSelection(
        selected=selected,
        score=selected.score,
        explanation=explanation,
        candidates=candidates,
    )


def _score(resume: Resume, job: Job, job_skills: set[str]) -> ResumeCandidate:
    reasons: list[str] = []
    score = 0

    role_points, role_note = _role_points(resume.target_role, job.title)
    score += role_points
    if role_note:
        reasons.append(role_note)

    skill_points, skill_note = _skill_points(resume, job_skills)
    score += skill_points
    if skill_note:
        reasons.append(skill_note)

    if resume.is_active:
        score += 15
        reasons.append("Active resume (+15).")
    else:
        reasons.append("Not the active resume.")

    if resume.version:
        score += 5
        reasons.append(f"Has a version marker ({resume.version}) (+5).")
    else:
        reasons.append("No version marker.")

    score = max(0, min(100, score))
    return ResumeCandidate(
        resume_id=resume.id,
        name=resume.name,
        target_role=resume.target_role,
        version=resume.version,
        is_active=bool(resume.is_active),
        score=score,
        reasons=reasons,
    )


def _role_points(target_role: str | None, job_title: str | None) -> tuple[int, str]:
    """Role overlap between the resume's target and the job title (max 45)."""
    if not target_role or not job_title:
        return 10, "No target role on resume to compare against the job title."
    job_key = norm.normalize_role(job_title)
    resume_key = norm.normalize_role(target_role)
    if job_key == resume_key:
        return 45, f"Target role exactly matches the job title ({target_role})."
    if job_key.startswith(resume_key) or resume_key.startswith(job_key):
        return 40, f"Target role overlaps the job title ({target_role})."
    job_words = set(job_key.split())
    resume_words = set(resume_key.split())
    overlap = len(job_words & resume_words)
    if overlap:
        return 30, f"Target role shares keywords with the job title ({target_role})."
    if _tech_family(target_role) and _tech_family(job_title):
        return 25, "Target role is in the same technical family as the job."
    return 10, f"Target role ({target_role}) does not obviously match the job."


def _skill_points(resume: Resume, job_skills: set[str]) -> tuple[int, str]:
    """Tech tokens present in the resume's metadata that the job lists."""
    if not job_skills:
        return 10, "Job lists no concrete skills to overlap against."
    text_terms = f"{resume.target_role or ''} {resume.name}"
    normalized = norm.normalize(text_terms)
    matched = sorted(s for s in job_skills if _word_in(s, normalized))
    if not matched:
        return 0, "No job-required skills appear in the resume metadata."
    fraction = min(1.0, len(matched) / max(1, len(job_skills)))
    points = round(25 * fraction)
    return points, f"Job skills found in resume metadata: {', '.join(matched)} (+{points})."


def _job_skill_keys(db, job: Job) -> set[str]:
    bundle = rex.extract_job_requirements(job)
    return {r.canonical for r in bundle.skills if r.canonical}


def _word_in(key: str, normalized_text: str) -> bool:
    pattern = rf"(?<![a-z0-9+.#]){key}s?(?![a-z0-9+.#])"
    return re.search(pattern, normalized_text) is not None or key in normalized_text


_TECH_HINT = re.compile(
    r"(software|engineer|developer|junior|full.?stack|frontend|backend|"
    r"java|react|python|dev|support|tester|qa|analyst|tech|systems|"
    r"programmer|code|web|it|infra|devops|sre|data|application)",
    re.I,
)


def _tech_family(term: str) -> bool:
    if not term:
        return False
    return _TECH_HINT.search(term) is not None
