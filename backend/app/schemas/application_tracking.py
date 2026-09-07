"""Request/response schemas for application tracking & analytics (Phase 8)."""
from datetime import date

from pydantic import BaseModel, Field


class StatusUpdateRequest(BaseModel):
    target_status: str = Field(min_length=1, max_length=40)
    override: bool = Field(default=False)
    notes: str | None = Field(default=None, max_length=2000)


class NoteAddRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=4000)


class ResponseCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    received_at: date
    notes: str | None = Field(default=None, max_length=2000)


class InterviewCreateRequest(BaseModel):
    interview_date: date
    interview_type: str = Field(default="OTHER", max_length=40)
    round_number: int = Field(default=1, ge=1)
    status: str = Field(default="SCHEDULED", max_length=30)
    notes: str | None = Field(default=None, max_length=2000)


class OfferCreateRequest(BaseModel):
    offer_date: date
    status: str = Field(default="RECEIVED", max_length=30)
    notes: str | None = Field(default=None, max_length=2000)


class FollowUpScheduleRequest(BaseModel):
    scheduled_date: date | None = Field(default=None)


class FollowUpCompleteRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class FollowUpRescheduleRequest(BaseModel):
    scheduled_date: date
    notes: str | None = Field(default=None, max_length=2000)


class FollowUpSkipRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class FollowUpRestoreRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)
