from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class MatchComponentRead(BaseModel):
    score: int | None = None
    status: str
    message: str = ""


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_score: float | None = None
    recommendation: str
    confidence_score: float | None = None
    matching_version: str
    criteria_breakdown: dict[str, MatchComponentRead] = {}
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    matched_requirements: list[dict] = []
    partial_requirements: list[dict] = []
    missing_requirements: list[dict] = []
    unknown_requirements: list[dict] = []
    evidence: list[str] = []
    explanation: list[dict] = []
    blockers: list[str] = []
    context_key: str | None = None
    profile_id: int | None = None
    calculated_at: datetime

    @model_validator(mode="after")
    def _derive_blockers(self) -> "MatchRead":
        if not self.blockers:
            self.blockers = [
                entry.get("message", "")
                for entry in self.explanation
                if entry.get("sentiment") == "blocker"
            ]
        return self


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_score: float | None = None
    quality_score: int | None = None
    freshness_score: int | None = None
    company_score: int | None = None
    opportunity_score: float
    recommendation: str
    opportunity_version: str
    explanation: list[dict] = []
    blockers: list[str] = []
    calculated_at: datetime
    profile_id: int | None = None


class MatchesStatsRead(BaseModel):
    average_match_score: int | None = None
    average_opportunity_score: int | None = None
    average_quality_score: int | None = None
    recommendation_counts: dict[str, int] = {}
    evaluated_jobs: int = 0
