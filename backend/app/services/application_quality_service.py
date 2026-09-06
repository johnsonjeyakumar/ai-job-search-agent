"""Quality gate and readiness for application packages (Phase 6).

Readiness measures packaging completeness and internal consistency only -- it
is NOT a hire probability. A package is READY when a resume is selected, every
required answer has a validated answer, and no truth/consistency finding is
open. The gate is FAIL on any INVALID finding, NEEDS_REVIEW while reviews are
pending, PASS otherwise. Coverage of the optional cover letter is not required.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.application_answers_service import REQUIRED_CATEGORIES
from app.services.application_validation_service import (
    INVALID,
    NEEDS_REVIEW,
)

GATE_FAIL = "FAIL"
GATE_NEEDS_REVIEW = "NEEDS_REVIEW"
GATE_PASS = "PASS"
READY = "READY"
NOT_READY = "NOT_READY"


@dataclass
class QualityResult:
    gate: str = GATE_NEEDS_REVIEW
    summary: str = ""
    readiness: str = NOT_READY
    readiness_reasons: list[str] = field(default_factory=list)


def evaluate(
    *,
    answers: list[dict],
    findings: list,
    selected_resume_id: int | None,
    cover_letter_status: str,
    match_score: float | None,
) -> QualityResult:
    """Compute the quality gate and readiness from validation findings."""
    reasons: list[str] = []
    gates: set[str] = set()

    for finding in findings:
        if finding.status == INVALID:
            gates.add(GATE_FAIL)
            reasons.append(finding.message)
        elif finding.status == NEEDS_REVIEW:
            gates.add(GATE_NEEDS_REVIEW)
            reasons.append(finding.message)

    if selected_resume_id is None:
        gates.add(GATE_NEEDS_REVIEW)
        reasons.append("No resume selected for the package.")

    required = {a["category"] for a in answers}
    unanswered = [c for c in REQUIRED_CATEGORIES if c not in required]
    if unanswered:
        gates.add(GATE_NEEDS_REVIEW)
        reasons.append(f"Missing required answers: {', '.join(unanswered)}.")

    empty_answers = [a["category"] for a in answers if not (a.get("answer") or "").strip()]
    if empty_answers:
        gates.add(GATE_NEEDS_REVIEW)
        reasons.append(f"Unanswered questions: {', '.join(empty_answers)}.")

    if GATE_FAIL in gates:
        gate = GATE_FAIL
    elif gates:
        gate = GATE_NEEDS_REVIEW
    else:
        gate = GATE_PASS

    readiness = READY if gate == GATE_PASS else NOT_READY
    if match_score is not None and match_score < 60 and gate != GATE_FAIL:
        reasons.append(
            f"Match score is {match_score:.0f} (below 60) -- consider revisiting this job."
        )

    summary = _summary(gate, reasons, cover_letter_status)
    return QualityResult(
        gate=gate,
        summary=summary,
        readiness=readiness,
        readiness_reasons=sorted(set(reasons)),
    )


def _summary(gate: str, reasons: list[str], cover_letter_status: str) -> str:
    if gate == GATE_FAIL:
        head = "This package cannot be approved: invalid content."
    elif gate == GATE_NEEDS_REVIEW:
        head = "This package needs review before it can be approved."
    else:
        head = "The package is complete, consistent, and ready for final review."
    parts = [head]
    if reasons:
        parts.append(" " + " ".join(reasons))
    if cover_letter_status == "skipped":
        parts.append(" No cover letter included (optional).")
    elif cover_letter_status == "needs_review":
        parts.append(" Cover letter was flagged for review.")
    return "".join(parts)
