from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ApplicationBase(BaseModel):
    job_id: int = Field(ge=1)
    profile_id: int | None = None
    resume_id: int | None = None
    # discovered | saved | applied | interviewing | offered | rejected | withdrawn
    status: str = Field(default="discovered", max_length=50)
    applied_date: date | None = None
    interview_date: date | None = None
    application_url: str | None = None
    notes: str | None = None


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationRead(ApplicationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
