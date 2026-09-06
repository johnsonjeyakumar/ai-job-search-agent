"""Validated AI output contracts for the application preparation engine (Phase 6).

Same architecture rule as Phase 5: the LLM never emits scores or
recommendations. It may only return generated words (answers, tailoring
suggestions, cover-letter text, validation findings) which are then
deterministically validated and stored. Every contract uses
``extra="forbid"`` so a payload carrying anything outside the documented
fields (e.g. ``match_score``, ``quality_gate``) is rejected wholesale and the
caller falls back to deterministic output.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AICoverLetter(BaseModel):
    """Cover-letter body only. No scores, no recommendation."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class AIApplicationAnswer(BaseModel):
    """One drafted application answer with the evidence it drew from."""

    model_config = ConfigDict(extra="forbid")

    category: str
    question: str
    answer: str
    source_evidence: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AITailoringSuggestion(BaseModel):
    """One resume tailoring suggestion grounded in existing evidence."""

    model_config = ConfigDict(extra="forbid")

    requirement: str
    suggested_wording: str
    reason: str = ""
    review_status: Literal["SAFE_TO_APPLY", "NEEDS_USER_REVIEW"] = "NEEDS_USER_REVIEW"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AIValidationFinding(BaseModel):
    """One truth/consistency finding from the AI reviewer."""

    model_config = ConfigDict(extra="forbid")

    check: str
    status: Literal["VALID", "NEEDS_REVIEW", "INVALID"]
    message: str = ""
