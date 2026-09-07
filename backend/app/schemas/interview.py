"""Request/response schemas for interview domain (Phase 10)."""
from datetime import date, datetime

from pydantic import BaseModel, Field


class InterviewCreateRequest(BaseModel):
    scheduled_at: datetime | None = None
    interview_type: str = Field(default="OTHER", max_length=40)
    round_number: int = Field(default=1, ge=1)
    interviewer_name: str | None = Field(default=None, max_length=255)
    interviewer_role: str | None = Field(default=None, max_length=255)
    meeting_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)


class InterviewUpdateRequest(BaseModel):
    scheduled_at: datetime | None = None
    interview_type: str | None = Field(default=None, max_length=40)
    interviewer_name: str | None = Field(default=None, max_length=255)
    interviewer_role: str | None = Field(default=None, max_length=255)
    meeting_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)


class InterviewStatusRequest(BaseModel):
    status: str = Field(..., max_length=30)
    notes: str | None = Field(default=None, max_length=4000)


class InterviewOutcomeRequest(BaseModel):
    outcome: str = Field(..., max_length=30)
    notes: str | None = Field(default=None, max_length=4000)


class InterviewFeedbackRequest(BaseModel):
    questions_asked: list[str] | None = None
    topics: list[str] | None = None
    difficulty: str | None = Field(default=None, max_length=20)
    personal_performance: str | None = Field(default=None, max_length=2000)
    interviewer_feedback: str | None = Field(default=None, max_length=2000)
    areas_to_improve: list[str] | None = None
    next_round: bool = Field(default=False)
    expected_response_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class InterviewRescheduleRequest(BaseModel):
    scheduled_at: datetime
    notes: str | None = Field(default=None, max_length=4000)


class QuestionGenerateRequest(BaseModel):
    categories: list[str] | None = None
    count: int = Field(default=10, ge=1, le=50)


class AnswerSaveRequest(BaseModel):
    draft_answer: str = Field(..., min_length=1, max_length=10000)


class MockSessionCreateRequest(BaseModel):
    interview_id: int | None = None
    question_count: int = Field(default=10, ge=1, le=30)
    technical_pct: int = Field(default=60, ge=0, le=100)
    behavioral_pct: int = Field(default=20, ge=0, le=100)
    project_pct: int = Field(default=20, ge=0, le=100)
    difficulty: str = Field(default="MEDIUM", max_length=10)


class MockAnswerRequest(BaseModel):
    question_index: int = Field(..., ge=0)
    answer: str = Field(..., min_length=1, max_length=10000)


class PrepItemUpdateRequest(BaseModel):
    status: str = Field(..., max_length=20)
