from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ResumeBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    profile_id: int | None = None
    target_role: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    is_active: bool = True


class ResumeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    target_role: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class ResumeRead(ResumeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str | None = None
    file_size: int | None = None
    content_type: str | None = None
    created_at: datetime
    updated_at: datetime
