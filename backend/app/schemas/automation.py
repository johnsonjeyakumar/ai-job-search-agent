from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_type: str
    job_source: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    jobs_found: int
    jobs_processed: int
    details: dict
    created_at: datetime
