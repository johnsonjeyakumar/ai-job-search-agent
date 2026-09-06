"""Validated AI output contract (Phase 5 architecture rule).

The LLM is never allowed to emit scores. It may only return structured facts
and interpretations that the deterministic scoring engine turns into scores.
This schema is the enforced contract:

- Any payload key outside this model (e.g. ``match_score``,
  ``opportunity_score``, ``recommendation``) makes validation FAIL via
  ``extra="forbid"``, so a misbehaving provider falls back to deterministic
  extraction instead of influencing a score.
- ``confidence`` is metadata only. It is surfaced for transparency but never
  multiplied into weights, so the same input always yields the same score.
"""
from pydantic import BaseModel, ConfigDict, Field


class AIJobInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_requirement: str | None = None
    role: str | None = None
    location: str | None = None
    education_requirement: str | None = None
    certifications: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
