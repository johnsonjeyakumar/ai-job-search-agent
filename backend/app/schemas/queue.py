"""Pydantic schemas for application queue and autopilot API."""
from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Queue schemas
# ---------------------------------------------------------------------------

class QueueItemResponse(BaseModel):
    id: int
    application_id: int
    package_id: int
    job_id: int
    queue_state: str
    attention: str | None = None
    attention_reason: str | None = None
    priority_score: float = 0.0
    match_score: float | None = None
    opportunity_score: float | None = None
    quality_score: float | None = None
    freshness_score: float | None = None
    job_title: str | None = None
    company_name: str | None = None
    platform: str | None = None
    resume_name: str | None = None
    execution_id: int | None = None
    autopilot_run_id: int | None = None
    resolution_data: dict = {}
    skip_reason: str | None = None
    error_message: str | None = None
    position: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}


class QueueListResponse(BaseModel):
    items: list[QueueItemResponse]
    total: int
    state_counts: dict[str, int] = {}
    attention_counts: dict[str, int] = {}


class QueueItemResolveRequest(BaseModel):
    resolution_data: dict = Field(default_factory=dict)


class QueueItemSkipRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class EnqueueRequest(BaseModel):
    application_id: int
    package_id: int
    job_id: int


class QueueStatsResponse(BaseModel):
    state_counts: dict[str, int] = {}
    attention_counts: dict[str, int] = {}
    pending_count: int = 0
    active_execution_count: int = 0
    daily_submitted: int = 0
    daily_target: int = 5
    daily_maximum: int = 10


# ---------------------------------------------------------------------------
# Autopilot schemas
# ---------------------------------------------------------------------------

class AutopilotStartRequest(BaseModel):
    target_count: int = Field(default=5, ge=1, le=50)


class AutopilotRunResponse(BaseModel):
    id: int
    status: str
    target_count: int = 0
    processed_count: int = 0
    submitted_count: int = 0
    blocked_count: int = 0
    review_count: int = 0
    input_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    current_queue_item_id: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AutopilotStatusResponse(BaseModel):
    active_run: AutopilotRunResponse | None = None
    pending_items: int = 0
    attention_counts: dict[str, int] = {}
    daily_submitted: int = 0
    daily_target: int = 5
    daily_maximum: int = 10


class AutopilotMessageResponse(BaseModel):
    status: str
    detail: str = ""
