from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class JobBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)

    location: str | None = Field(default=None, max_length=255)
    remote_type: str | None = Field(default=None, max_length=50)
    employment_type: str | None = Field(default=None, max_length=50)
    experience_required: str | None = Field(default=None, max_length=100)
    salary: str | None = Field(default=None, max_length=255)
    description: str | None = None
    requirements: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    url: str | None = None
    source: str = Field(default="unknown", min_length=1, max_length=100)
    source_job_id: str | None = Field(default=None, max_length=255)
    posted_date: date | None = None
    application_url: str | None = None
    company_url: str | None = None


class JobCreate(JobBase):
    pass


class JobRead(JobBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    discovered_date: datetime


class JobListResponse(BaseModel):
    items: list[JobRead]
    page: int
    limit: int
    total: int
    pages: int


class JobSearchRequest(BaseModel):
    """Optional overrides for a discovery run. Missing values use stored preferences."""

    locations: list[str] | None = None
    roles: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=100)


class JobSearchResponse(BaseModel):
    status: str
    run_id: int
