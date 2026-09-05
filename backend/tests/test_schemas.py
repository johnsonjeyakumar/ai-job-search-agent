import pytest
from pydantic import ValidationError

from app.schemas.job import JobCreate
from app.schemas.profile import ProfileCreate


def test_profile_schema_valid():
    profile = ProfileCreate(
        name="Jane Doe",
        email="jane@example.com",
        skills=["Python", "React"],
        preferred_roles=["Full Stack Developer"],
        preferred_locations=["Chennai", "Remote India"],
    )
    assert profile.skills == ["Python", "React"]
    assert profile.preferred_roles == ["Full Stack Developer"]
    assert profile.remote_preference is None


def test_profile_schema_invalid_email():
    with pytest.raises(ValidationError):
        ProfileCreate(name="Jane Doe", email="not-an-email")


def test_profile_schema_invalid_graduation_year():
    with pytest.raises(ValidationError):
        ProfileCreate(name="Jane", email="j@e.com", graduation_year=1800)


def test_profile_schema_empty_name():
    with pytest.raises(ValidationError):
        ProfileCreate(name="", email="j@e.com")


def test_job_schema_valid_with_defaults():
    job = JobCreate(
        title="Backend Developer",
        company="Acme",
        location="Chennai",
        skills=["Python"],
    )
    assert job.company == "Acme"
    assert job.source == "unknown"
    assert job.requirements == []


def test_job_schema_missing_title():
    with pytest.raises(ValidationError):
        JobCreate(company="Acme")


def test_job_schema_missing_company():
    with pytest.raises(ValidationError):
        JobCreate(title="Developer")


def test_job_model_mapping(db_session):
    from app.models.job import Job

    job = Job(
        title="Frontend Developer",
        company="Acme",
        location="Remote India",
        source="test-source",
        source_job_id="job-1",
        skills=["React"],
    )
    db_session.add(job)
    db_session.flush()
    assert job.id is not None
    assert job.source == "test-source"
    assert job.source_job_id == "job-1"
