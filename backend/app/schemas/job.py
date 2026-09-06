from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.match import MatchesStatsRead, MatchRead, OpportunityRead


class FreshnessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    age_in_days: int | None = None
    score: int | None = None
    as_of: datetime
    explanation: str


class QualityComponentRead(BaseModel):
    score: int | None = None
    label: str
    message: str = ""
    sentiment: str = "info"


class QualityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    overall_score: int
    scoring_version: str
    components: dict[str, QualityComponentRead]
    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)
    calculated_at: datetime


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    normalized_name: str
    display_name: str | None = None
    domain: str | None = None
    website: str | None = None
    careers_url: str | None = None
    industry: str | None = None
    company_size: str | None = None
    first_seen_job_at: datetime | None = None
    last_seen_job_at: datetime | None = None
    active_job_count: int = 0
    distinct_role_count: int = 0
    source_count: int = 0


class JobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    event_type: str
    event_data: dict = Field(default_factory=dict)
    created_at: datetime


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
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    freshness: FreshnessRead | None = None
    quality: QualityRead | None = None
    match: MatchRead | None = None
    opportunity: OpportunityRead | None = None
    company_info: CompanyRead | None = None
    recent_events: list[JobEventRead] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[JobRead]
    page: int
    limit: int
    total: int
    pages: int


class JobStatsResponse(BaseModel):
    total: int
    freshness_counts: dict[str, int]
    avg_quality: int | None
    top_companies: list[dict]
    matches: MatchesStatsRead = Field(default_factory=MatchesStatsRead)
    computed_at: datetime


class CompanyListResponse(BaseModel):
    items: list[CompanyRead]
    total: int


class JobSearchRequest(BaseModel):
    """Optional overrides for a discovery run. Missing values use stored preferences."""

    locations: list[str] | None = None
    roles: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=100)


class JobSearchResponse(BaseModel):
    status: str
    run_id: int
