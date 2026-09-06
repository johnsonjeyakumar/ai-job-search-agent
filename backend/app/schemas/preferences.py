from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PREFERRED_LOCATIONS = ["Chennai", "Madurai", "Remote - India"]
DEFAULT_EXPERIENCE_LEVELS = ["Fresher", "0-2 years"]
DEFAULT_TARGET_ROLES = [
    "Software Developer",
    "Full Stack Developer",
    "Frontend Developer",
    "Backend Developer",
    "Java Developer",
    "React Developer",
    "Junior Software Engineer",
    "Technical Support Engineer",
]
DEFAULT_REMOTE_TYPES = ["remote", "hybrid", "onsite"]
DEFAULT_EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "internship"]


class PreferencesBase(BaseModel):
    preferred_locations: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PREFERRED_LOCATIONS)
    )
    experience_levels: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXPERIENCE_LEVELS)
    )
    target_roles: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGET_ROLES))
    remote_types: list[str] = Field(default_factory=lambda: list(DEFAULT_REMOTE_TYPES))
    employment_types: list[str] = Field(default_factory=lambda: list(DEFAULT_EMPLOYMENT_TYPES))

    min_match_score: int = Field(default=60, ge=0, le=100)
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    posted_within_days: int = Field(default=30, ge=1, le=365)

    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    # Phase 7 application execution controls.
    daily_application_target: int | None = Field(default=None, ge=0)
    daily_application_maximum: int | None = Field(default=None, ge=0)
    # {"platform": "AUTHORIZED_AUTOMATION|PERMITTED_BROWSER|HUMAN_ASSISTED|UNSUPPORTED"}
    platform_policies: dict = Field(default_factory=dict)


class PreferencesUpdate(PreferencesBase):
    """Same as base — every field is optional in practice because PUT replaces."""


class PreferencesRead(PreferencesBase):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    profile_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
