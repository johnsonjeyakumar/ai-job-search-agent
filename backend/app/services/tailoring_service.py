"""Resume tailoring suggestions (Phase 6).

Suggestions either re-frame evidence that already exists (``SAFE_TO_APPLY``)
or require the user to verify before anything new is claimed
(``NEEDS_USER_REVIEW``). The original resume is never modified; a suggestion
never fabricates facts. AI wording is validated against
``AITailoringSuggestion`` (``extra="forbid"``) and any wording that would
assert a fact with no backing evidence is forced to ``NEEDS_USER_REVIEW``.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.services.application_evidence_service import (
    STATUS_MATCHED,
    STATUS_MISSING_EVIDENCE,
    STATUS_UNKNOWN,
    EvidenceEntry,
)
from app.services.application_truthfulness import asserts_new_fact

SAFE_TO_APPLY = "SAFE_TO_APPLY"
NEEDS_USER_REVIEW = "NEEDS_USER_REVIEW"


@dataclass
class TailoringSuggestion:
    requirement: str
    category: str
    existing_evidence: str | None
    suggested_wording: str
    reason: str
    review_status: str = NEEDS_USER_REVIEW
    confidence: str = "LOW"
    resume_id: int | None = None


async def generate_tailoring_suggestions(
    db,
    job: Job,
    profile: Profile | None,
    resume: Resume | None,
    evidence_entries: list[EvidenceEntry],
) -> list[TailoringSuggestion]:
    """Deterministic suggestions, optionally enriched by a validated AI pass."""
    suggestions = [_deterministic(e, resume) for e in evidence_entries]
    suggestions = [s for s in suggestions if s is not None]
    suggestions.extend(await _ai_suggestions(db, job, profile, resume, evidence_entries))
    return suggestions


def _deterministic(
    entry: EvidenceEntry, resume: Resume | None
) -> TailoringSuggestion | None:
    if entry.status == STATUS_MATCHED:
        return None
    term = entry.requirement
    if entry.status == STATUS_MISSING_EVIDENCE:
        return TailoringSuggestion(
            requirement=term,
            category=entry.category,
            existing_evidence=None,
            suggested_wording=(
                f"Do not claim '{term}' on the resume: no evidence is stored "
                f"for it. Add it only after real proof (coursework, project, "
                f"or certification) exists."
            ),
            reason="No stored evidence for this requirement",
            review_status=SAFE_TO_APPLY,
            confidence="HIGH",
            resume_id=resume.id if resume is not None else None,
        )
    if entry.evidence:
        return TailoringSuggestion(
            requirement=term,
            category=entry.category,
            existing_evidence=entry.evidence,
            suggested_wording=(
                f"Highlight existing evidence on the resume: '{entry.evidence}'. "
                f"Lead the line with what you actually did."
            ),
            reason="Existing evidence can be surfaced",
            review_status=SAFE_TO_APPLY,
            confidence="HIGH" if entry.confidence == "HIGH" else "MEDIUM",
            resume_id=resume.id if resume is not None else None,
        )
    if entry.status == STATUS_UNKNOWN:
        return TailoringSuggestion(
            requirement=term,
            category=entry.category,
            existing_evidence=None,
            suggested_wording=(
                f"Confirm how you meet '{term}' yourself; the stored data "
                f"cannot verify it either way."
            ),
            reason="Cannot be verified from stored data",
            review_status=NEEDS_USER_REVIEW,
            confidence="LOW",
            resume_id=resume.id if resume is not None else None,
        )
    return TailoringSuggestion(
        requirement=term,
        category=entry.category,
        existing_evidence=None,
        suggested_wording=(
            f"Do not claim '{term}' on the resume until evidence exists."
        ),
        reason="No verified evidence",
        review_status=NEEDS_USER_REVIEW,
        confidence="LOW",
        resume_id=resume.id if resume is not None else None,
    )


async def _ai_suggestions(
    db,
    job: Job,
    profile: Profile | None,
    resume: Resume | None,
    evidence_entries: list[EvidenceEntry],
) -> list[TailoringSuggestion]:
    from pydantic import ValidationError

    from app.ai.registry import get_provider
    from app.schemas.ai_application import AITailoringSuggestion

    provider = get_provider()
    if provider.name == "mock":
        return []
    gaps = [
        {
            "requirement": e.requirement,
            "category": e.category,
            "status": e.status,
            "evidence": e.evidence,
        }
        for e in evidence_entries
        if e.status != STATUS_MATCHED
    ]
    payload = await provider.suggest_tailoring(job, profile, resume, gaps)
    if not payload:
        return []
    suggestions: list[TailoringSuggestion] = []
    for item in payload:
        try:
            parsed = AITailoringSuggestion.model_validate(item)
        except (ValidationError, TypeError, ValueError):
            continue
        review = parsed.review_status
        if asserts_new_fact(parsed.suggested_wording, profile, resume, set()):
            review = NEEDS_USER_REVIEW
        suggestions.append(
            TailoringSuggestion(
                requirement=parsed.requirement or "",
                category="skill" if not parsed.requirement else "",
                existing_evidence=None,
                suggested_wording=parsed.suggested_wording,
                reason=parsed.reason or "AI-suggested wording",
                review_status=review,
                confidence=_map_confidence(parsed.confidence),
                resume_id=resume.id if resume is not None else None,
            )
        )
    return suggestions


def _map_confidence(value: float | None) -> str:
    if value is None:
        return "LOW"
    if value >= 0.8:
        return "HIGH"
    if value >= 0.5:
        return "MEDIUM"
    return "LOW"
