"""API schemas for the application preparation engine (Phase 6)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApplicationPrepareRequest(BaseModel):
    job_id: int = Field(ge=1)
    include_cover_letter: bool = False


class PackageSummary(BaseModel):
    id: int
    job_id: int
    job_title: str | None = None
    company: str | None = None
    resume_name: str | None = None
    version: int
    status: str
    readiness: str
    quality_gate: str
    match_score: float | None = None
    opportunity_score: float | None = None
    recommendation: str | None = None
    created_at: datetime
    updated_at: datetime


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    question: str
    answer: str | None
    source_evidence: list
    confidence: str
    validation_status: str
    feedback: str | None


class AnswerUpdateRequest(BaseModel):
    answer_text: str = Field(min_length=1)


class CoverLetterUpdateRequest(BaseModel):
    text: str | None = None


class PackagePrepareResponse(BaseModel):
    package: PackageSummary
    duplicate_disclaimer: str | None = None
    created: bool


class PackageActionResponse(BaseModel):
    package: PackageSummary
    message: str
