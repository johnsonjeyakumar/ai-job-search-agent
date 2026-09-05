from datetime import datetime

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)


class ProjectItem(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    url: AnyUrl | None = None


class InternshipItem(BaseModel):
    company: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    duration: str | None = Field(default=None, max_length=100)
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)


class CertificationItem(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    issuer: str | None = Field(default=None, max_length=255)
    date: str | None = Field(default=None, max_length=50)
    credential_url: AnyUrl | None = None


class ProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr

    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=255)
    linkedin_url: AnyUrl | None = None
    github_url: AnyUrl | None = None
    portfolio_url: AnyUrl | None = None

    education: str | None = Field(default=None, max_length=255)  # legacy
    degree: str | None = Field(default=None, max_length=255)
    university: str | None = Field(default=None, max_length=255)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    cgpa: str | None = Field(default=None, max_length=50)

    skills: list[str] = Field(default_factory=list)  # aggregate (server-derived)
    skills_programming: list[str] = Field(default_factory=list)
    skills_frameworks: list[str] = Field(default_factory=list)
    skills_databases: list[str] = Field(default_factory=list)
    skills_tools: list[str] = Field(default_factory=list)
    skills_other: list[str] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    internships: list[InternshipItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)

    experience_level: str | None = Field(default=None, max_length=100)
    preferred_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: str | None = Field(default=None, max_length=50)
    salary_preference: str | None = Field(default=None, max_length=255)
    notice_period: str | None = Field(default=None, max_length=100)
    work_authorization: str | None = Field(default=None, max_length=255)


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(ProfileBase):
    """All fields optional; only provided fields are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None

    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=255)
    linkedin_url: AnyUrl | None = None
    github_url: AnyUrl | None = None
    portfolio_url: AnyUrl | None = None

    education: str | None = Field(default=None, max_length=255)
    degree: str | None = Field(default=None, max_length=255)
    university: str | None = Field(default=None, max_length=255)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    cgpa: str | None = Field(default=None, max_length=50)

    skills: list[str] | None = None
    skills_programming: list[str] | None = None
    skills_frameworks: list[str] | None = None
    skills_databases: list[str] | None = None
    skills_tools: list[str] | None = None
    skills_other: list[str] | None = None
    projects: list[ProjectItem] | None = None
    internships: list[InternshipItem] | None = None
    certifications: list[CertificationItem] | None = None

    experience_level: str | None = Field(default=None, max_length=100)
    preferred_roles: list[str] | None = None
    preferred_locations: list[str] | None = None
    remote_preference: str | None = Field(default=None, max_length=50)
    salary_preference: str | None = Field(default=None, max_length=255)
    notice_period: str | None = Field(default=None, max_length=100)
    work_authorization: str | None = Field(default=None, max_length=255)


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
