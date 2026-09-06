"""API schemas for application execution (Phase 7)."""
from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    driver: str = Field(default="auto", pattern=r"^(auto|mock|playwright)$")
    force_duplicate: bool = False


class CancelExecutionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ConfirmSubmissionRequest(BaseModel):
    verification: str = Field(
        default="LIKELY", pattern=r"^(CONFIRMED|LIKELY|UNKNOWN|FAILED)$"
    )
    reference: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class ExecutionMessageResponse(BaseModel):
    execution_id: int
    status: str
    detail: str = ""
