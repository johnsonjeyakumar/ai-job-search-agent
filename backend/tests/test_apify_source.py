"""Tests for the Apify job source (normalization, validation, params)."""
from datetime import date

import pytest

from app.job_sources import ApifyJobSource, JobSourceError

INDEEd_SAMPLE = {
    "jobKey": "jk_a1b2c3d4",
    "position": "Software Developer",
    "company": "  Acme  Corp  ",
    "location": "Chennai, Tamil Nadu",
    "workplaceType": "Hybrid",
    "employmentType": "Full-time",
    "salary": {"text": "₹8,00,000 - ₹12,00,000 per year"},
    "descriptionText": "Build great software.\n- Python\n- FastAPI",
    "jobUrl": "https://in.indeed.com/viewjob?jk=a1b2c3d4",
    "applyUrl": "https://in.indeed.com/cmp/acme/apply?jk=a1b2c3d4",
    "companyUrl": "https://in.indeed.com/cmp/acme",
    "listedAtISO": "2026-09-02T10:00:00.000Z",
}


def _source() -> ApifyJobSource:
    return ApifyJobSource(token="test-token")


def test_build_search_params_uses_preferences():
    source = _source()
    prefs = {
        "target_roles": ["Software Developer", "Backend Developer"],
        "preferred_locations": ["Chennai", "Madurai", "Remote - India", "Pune"],
        "posted_within_days": 14,
        "remote_types": ["remote", "hybrid"],
        "max_items": 0,
    }
    params = source.build_search_params(prefs, limit=12)
    assert params["maxItems"] == 12
    assert len(params["searches"]) == 3  # capped at _MAX_LOCATIONS
    assert params["searches"][0]["query"] == "Software Developer"
    assert params["searches"][0]["location"] == "Chennai"
    assert params["searches"][0]["country"] == "in"
    assert params["searches"][0]["sort"] == "relevance"
    assert "postedWithinDays" not in params["searches"][0]  # freshness applied post-storage
    assert "remoteOnly" not in params["searches"][0]  # not only-remote prefs


def test_build_search_params_remote_only():
    source = _source()
    params = source.build_search_params(
        {
            "target_roles": ["React Developer"],
            "preferred_locations": ["Chennai"],
            "remote_types": ["remote"],
        },
        limit=20,
    )
    assert params["searches"][0]["remoteOnly"] is True


def test_build_search_params_no_locations_falls_back():
    source = _source()
    params = source.build_search_params({"target_roles": []}, limit=20)
    assert params["searches"][0]["query"] == "Software Developer"
    assert params["searches"][0]["country"] == "in"


def test_normalize_job_indeed_sample():
    source = _source()
    job = source.normalize_job(dict(INDEEd_SAMPLE))
    assert job["title"] == "Software Developer"
    assert job["company"] == "Acme Corp"
    assert job["location"] == "Chennai, Tamil Nadu"
    assert job["remote_type"] == "hybrid"
    assert job["employment_type"] == "full_time"
    assert job["source_job_id"] == "jk_a1b2c3d4"
    assert job["posted_date"].isoformat() == "2026-09-02"
    assert job["salary"] == "₹8,00,000 - ₹12,00,000 per year"
    assert job["url"] == "https://in.indeed.com/viewjob?jk=a1b2c3d4"
    assert job["application_url"].startswith("https://in.indeed.com/cmp/acme/apply")
    assert job["company_url"] == "https://in.indeed.com/cmp/acme"
    assert job["description"] == "Build great software.\n- Python\n- FastAPI"
    assert "Python" in job["requirements"]


def test_normalize_job_missing_optional_fields_is_null_safe():
    source = _source()
    job = source.normalize_job({"position": "Frontend Developer", "company": "X"})
    assert job["remote_type"] is None
    assert job["employment_type"] is None
    assert job["salary"] is None
    assert job["posted_date"] is None
    assert job["url"] is None
    assert job["application_url"] is None
    assert job["company_url"] is None


def test_normalize_job_null_salary_dict_yields_none():
    source = _source()
    job = source.normalize_job({
        "position": "Dev",
        "company": "X",
        "salary": {"min": None, "max": None, "text": None},
        "jobUrl": "https://in.indeed.com/viewjob?jk=sal1",
    })
    assert job["salary"] is None


def test_source_job_id_derivation_without_key():
    source = _source()
    job = source.normalize_job(
        {"position": "Dev", "company": "C", "jobUrl": "https://in.indeed.com/viewjob?jk=xyz"}
    )
    assert job["source_job_id"].startswith("derived:")


def test_normalize_job_prefers_full_location_over_split_parts():
    source = _source()
    job = source.normalize_job({
        "position": "Software Engineer",
        "company": "X",
        "location": "Chennai, Tamil Nadu",
        "city": None,
        "state": "TN",
        "country": "IN",
        "remote": False,
        "remoteWorkType": "UNKNOWN",
        "jobUrl": "https://in.indeed.com/viewjob?jk=test123",
    })
    assert job["location"] == "Chennai, Tamil Nadu"


# Realistic sample of the schnellscrapers/indeed-jobs-scraper output shape.
REAL_ACTOR_SAMPLE = {
    "url": "https://in.indeed.com/viewjob?jk=realjk123",
    "jobKey": "realjk123",
    "expired": False,
    "title": "Software Developer",
    "company": "Tech Solutions Pvt Ltd",
    "location": "Chennai, Tamil Nadu",
    "salaryText": "₹6,00,000 - ₹9,00,000 a year",
    "employmentType": "Full-time",
    "workplaceType": None,
    "postingDateParsed": "2026-09-04T00:00:00.000Z",
    "postedAt": "2026-09-05T05:00:00.000Z",
    "postedRelative": "1 day ago",
    "hiringOrganization": {"name": "Tech Solutions Pvt Ltd", "sameAs": ""},
    "companyIndeedUrl": "https://www.indeed.com/cmp/tech-solutions",
    "applyUrl": "https://in.indeed.com/cmp/tech-solutions/apply?jk=realjk123",
    "descriptionText": "We build products for finance teams.\n- Python\n- FastAPI",
}


def test_normalize_job_posting_date_from_posting_date_parsed():
    source = _source()
    job = source.normalize_job(dict(REAL_ACTOR_SAMPLE))
    assert job["posted_date"] == date(2026, 9, 4)


def test_normalize_job_posting_date_from_posted_at():
    source = _source()
    raw = dict(REAL_ACTOR_SAMPLE)
    raw.pop("postingDateParsed")
    job = source.normalize_job(raw)
    assert job["posted_date"] == date(2026, 9, 5)


def test_normalize_job_posting_date_precedence():
    # postingDateParsed is the most reliable parsed date and must win.
    source = _source()
    job = source.normalize_job(dict(REAL_ACTOR_SAMPLE))
    assert job["posted_date"] == date(2026, 9, 4)


def test_normalize_job_invalid_dates_are_not_invented():
    source = _source()
    raw = {
        "jobKey": "k1",
        "position": "Dev",
        "company": "X",
        "postedAt": "2 days ago",
        "postingDateParsed": "Updated on 5 Sep",
    }
    job = source.normalize_job(raw)
    assert job["posted_date"] is None


def test_normalize_job_missing_date_is_null():
    source = _source()
    job = source.normalize_job({"jobKey": "k2", "position": "Dev", "company": "X"})
    assert job["posted_date"] is None


def test_normalize_job_company_indeed_url_to_company_url():
    source = _source()
    job = source.normalize_job(dict(REAL_ACTOR_SAMPLE))
    assert job["company_url"] == "https://www.indeed.com/cmp/tech-solutions"


def test_normalize_job_company_url_alias_still_supported():
    source = _source()
    raw = dict(REAL_ACTOR_SAMPLE)
    raw.pop("companyIndeedUrl")
    raw["companyUrl"] = "https://in.indeed.com/cmp/tech-solutions"
    job = source.normalize_job(raw)
    assert job["company_url"] == "https://in.indeed.com/cmp/tech-solutions"


def test_normalize_job_company_url_rejects_non_http():
    source = _source()
    raw = dict(REAL_ACTOR_SAMPLE)
    raw["companyIndeedUrl"] = "javascript:alert(1)"
    job = source.normalize_job(raw)
    assert job["company_url"] is None


def test_validate_job():
    source = _source()
    ok, reason = source.validate_job(source.normalize_job(dict(INDEEd_SAMPLE)))
    assert ok and reason == ""

    empty_title = source.normalize_job({"company": "X"})
    assert source.validate_job(empty_title) == (False, "missing title")

    no_id_no_url = source.normalize_job({"position": "T", "company": "C"})
    assert source.validate_job(no_id_no_url) == (True, "")  # derived id provides dedup key

    bad_url = source.normalize_job(
        {"position": "T", "company": "C", "jobUrl": "ftp://bad", "jobKey": "k"}
    )
    assert bad_url["url"] is None  # bad scheme is never stored

    crafted = source.normalize_job(dict(INDEEd_SAMPLE))
    crafted["url"] = "ftp://bad"
    assert source.validate_job(crafted)[1] == "invalid url"


def test_search_jobs_returns_valid_and_invalid():
    source = _source()
    raw = [dict(INDEEd_SAMPLE), {"foo": "no title here"}]
    source.search = lambda params: raw
    result = source.search_jobs(
        {"target_roles": ["Software Developer"], "preferred_locations": ["Chennai"]},
        limit=10,
    )
    assert result.raw_count == 2
    assert len(result.jobs) == 1
    assert len(result.invalid) == 1
    assert result.invalid[0]["reason"] == "missing title"
    assert result.jobs[0]["source"] == "apify"


def test_search_requires_token(monkeypatch):
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "apify_token", "")
    source = ApifyJobSource(token="")
    with pytest.raises(JobSourceError):
        source.search({})
