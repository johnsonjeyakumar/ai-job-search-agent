"""Phase 4: freshness, lifecycle events, company intelligence, quality scores."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.job import Job
from app.models.quality import JobQualityScore
from app.services import (
    company_service,
    freshness_service,
    job_events_service,
    job_quality_service,
    job_service,
)

UTC = timezone.utc


def _build_job(title, company, **extra):
    return {
        "title": title,
        "company": company,
        "source": "apify",
        "source_job_id": extra.pop("source_job_id", None),
        "url": extra.pop("url", None),
        "location": extra.pop("location", "Chennai, Tamil Nadu"),
        "remote_type": extra.pop("remote_type", None),
        "employment_type": extra.pop("employment_type", None),
        "salary": extra.pop("salary", None),
        "description": extra.pop("description", None),
        "requirements": extra.pop("requirements", []),
        "skills": extra.pop("skills", []),
        "application_url": extra.pop("application_url", None),
        "company_url": extra.pop("company_url", None),
        "posted_date": extra.pop("posted_date", None),
        **extra,
    }


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------
class TestFreshnessBands:
    def test_boundaries(self):
        cases = {
            None: ("UNKNOWN", None),
            0: ("VERY_FRESH", 100),
            2: ("VERY_FRESH", 100),
            3: ("VERY_FRESH", 100),
            4: ("FRESH", 90),
            7: ("FRESH", 90),
            8: ("RECENT", 75),
            14: ("RECENT", 75),
            15: ("AGING", 50),
            30: ("AGING", 50),
            31: ("STALE", 20),
            60: ("STALE", 20),
        }
        for age_in_days, (status, score) in cases.items():
            posted = None if age_in_days is None else date.today() - timedelta(days=age_in_days)
            info = freshness_service.classify(posted, as_of=datetime.now(UTC))
            assert info.status == status, f"age {age_in_days}"
            assert info.score == score, f"age {age_in_days}"

    def test_age_clamped_for_future_postings(self):
        posted = date.today() + timedelta(days=2)
        info = freshness_service.classify(posted, as_of=datetime.now(UTC))
        assert info.age_in_days == 0
        assert info.status == "VERY_FRESH"

    def test_unknown_explanation(self):
        info = freshness_service.classify(None, as_of=datetime.now(UTC))
        assert info.explanation == "Posting date unknown"

    def test_age_range_windows(self):
        assert freshness_service.age_range("VERY_FRESH") == (0, 3)
        assert freshness_service.age_range("FRESH") == (4, 7)
        assert freshness_service.age_range("RECENT") == (8, 14)
        assert freshness_service.age_range("AGING") == (15, 30)
        assert freshness_service.age_range("stale") == (31, None)
        assert freshness_service.age_range("UNKNOWN") is None
        with pytest.raises(ValueError):
            freshness_service.age_range("BOGUS")


# ---------------------------------------------------------------------------
# Lifecycle / events
# ---------------------------------------------------------------------------
def _one_job(db_session, **extra):
    sid = extra.pop("source_job_id", "lc-1")
    record = _build_job(
        "Full Stack Engineer",
        extra.pop("company", "Acme Corp"),
        source_job_id=sid,
        **extra,
    )
    result = job_service.insert_jobs(db_session, [record], source="apify")
    assert result.inserted == 1
    job = db_session.scalar(select(Job).where(Job.source_job_id == sid))
    assert job is not None
    return job


class TestLifecycle:
    def test_discovery_sets_timestamps_and_events(self, db_session):
        job = _one_job(db_session)
        assert job.first_seen_at is not None
        assert job.last_seen_at is not None
        assert job.first_seen_at == job.last_seen_at
        events = job_events_service.recent_events(db_session, job.id)
        assert [e.event_type for e in events] == ["DISCOVERED"]

    def test_rediscovery_advances_last_seen(self, db_session):
        job = _one_job(db_session)
        first = job.last_seen_at
        record = _build_job(
            "Full Stack Engineer", "Acme Corp", source_job_id="lc-1"
        )
        job_service.insert_jobs(db_session, [record], source="apify")
        assert job.last_seen_at >= first
        assert len(job_events_service.recent_events(db_session, job.id)) == 1

    def test_update_emits_changed_fields(self, db_session):
        job = _one_job(db_session, salary=None)
        record = _build_job(
            "Full Stack Engineer",
            "Acme Corp",
            source_job_id="lc-1",
            salary="$90k",
        )
        result = job_service.insert_jobs(db_session, [record], source="apify")
        assert result.duplicates == 1
        assert job.salary == "$90k"
        events = job_events_service.recent_events(db_session, job.id)
        assert events[0].event_type == "UPDATED"
        changes = events[0].event_data["changes"]
        assert changes["salary"]["after"] == "$90k"

    def test_reappeared_after_gap_without_change(self, db_session):
        job = _one_job(db_session)
        job.last_seen_at = datetime.now(UTC) - timedelta(days=2)
        db_session.flush()
        record = _build_job(
            "Full Stack Engineer", "Acme Corp", source_job_id="lc-1"
        )
        job_service.insert_jobs(db_session, [record], source="apify")
        events = job_events_service.recent_events(db_session, job.id)
        assert events[0].event_type == "REAPPEARED"

    def test_expired_never_auto_emitted(self, db_session):
        job = _one_job(db_session)
        record = _build_job(
            "Full Stack Engineer", "Acme Corp", source_job_id="lc-1"
        )
        job_service.insert_jobs(db_session, [record], source="apify")
        events = job_events_service.recent_events(db_session, job.id)
        assert all(e.event_type != "EXPIRED" for e in events)


# ---------------------------------------------------------------------------
# Company intelligence
# ---------------------------------------------------------------------------
class TestCompany:
    def test_normalized_key_strips_legal_suffixes(self):
        assert company_service.normalize_company_name("Acme Corp") == "acme"
        assert (
            company_service.normalize_company_name("Acme Technologies Pvt Ltd")
            == "acme technologies"
        )
        assert company_service.normalize_company_name(" ACME CORPORATION ") == "acme"
        assert company_service.normalize_company_name("Acme " "co.") == "acme"
        assert company_service.normalize_company_name("  ") is None

    def test_no_weak_merges(self):
        a = company_service.normalize_company_name("Acme Corp")
        b = company_service.normalize_company_name("Acme Technologies")
        assert a != b  # exact-key matching only

    def test_domain_only_from_company_owned_url(self):
        assert company_service._trusted_domain("https://www.acme.com") == (
            "acme.com",
            "https://www.acme.com",
        )
        assert company_service._trusted_domain("https://in.indeed.com/cmp/acme") == (
            None,
            None,
        )
        assert company_service._trusted_domain("https://linkedin.com/company/acme") == (
            None,
            None,
        )
        assert company_service._trusted_domain("not a url") == (None, None)

    def test_upsert_creates_company_and_derives_domain(self, db_session):
        _one_job(
            db_session,
            company="Acme Corporation",
            company_url="https://www.acme.com/careers",
            source_job_id="cmp-1",
        )
        company = company_service.find_company(db_session, "Acme Corporation")
        assert company is not None
        assert company.normalized_name == "acme"
        assert company.domain == "acme.com"
        assert company.website == "https://www.acme.com/careers"
        assert company.first_seen_job_at is not None
        assert company.last_seen_job_at is not None

    def test_aggregates_from_jobs(self, db_session):
        job_service.insert_jobs(
            db_session,
            [
                _build_job("Dev 1", "Acme Corp", source_job_id="agg-1"),
                _build_job("Dev 1", "Acme Corp", source_job_id="agg-2", url="https://x.test/a"),
                _build_job("QA", "Beta LLC", source_job_id="agg-3", url="https://x.test/b"),
            ],
            source="apify",
        )
        counts = company_service.job_aggregates(db_session)
        acme = counts["acme"]
        assert acme["active_job_count"] == 2
        assert acme["distinct_role_count"] == 1
        assert acme["source_count"] == 1
        assert counts["beta"]["active_job_count"] == 1


# ---------------------------------------------------------------------------
# Quality scores
# ---------------------------------------------------------------------------
class TestQuality:
    def test_weights_sum_to_one(self):
        weights = job_quality_service.weights()
        assert sum(weights.values()) == pytest.approx(1.0)
        assert set(weights) == set(job_quality_service.LABELS)

    def test_component_scores(self, db_session):
        job = _one_job(
            db_session,
            description="x" * 500,
            requirements=["a", "b", "c"],
            application_url="https://jobs.acme.com/apply",
            salary="INR 2,00,000",
            company_url="https://www.acme.com",
            source_job_id="q-1",
        )
        result = job_quality_service.calculate(db_session, job, store=False)
        assert result.components["description"]["score"] == 100
        assert result.components["requirements"]["score"] == 80
        assert result.components["application"]["score"] == 100
        assert result.components["company"]["score"] == 85  # 40 + 25 (site) + 20 (domain)
        assert result.components["location"]["score"] == 100
        assert result.components["salary"]["score"] == 100
        assert 90 <= result.overall_score <= 100

    def test_missing_salary_is_mid_not_zero(self, db_session):
        job = _one_job(db_session, salary=None, source_job_id="q-2")
        result = job_quality_service.calculate(db_session, job, store=False)
        assert result.components["salary"]["score"] == 40
        assert result.components["salary"]["message"] == "Salary not listed"

    def test_unknown_freshness_excluded_from_denominator(self, db_session):
        job = _one_job(
            db_session,
            posted_date=None,
            salary=None,
            description=None,
            source_job_id="q-3",
        )
        result = job_quality_service.calculate(db_session, job, store=False)
        assert result.components["freshness"]["score"] is None
        assert 0 <= result.overall_score <= 100

    def test_determinism(self, db_session):
        job = _one_job(db_session, source_job_id="q-4")
        a = job_quality_service.calculate(db_session, job, store=False)
        b = job_quality_service.calculate(db_session, job, store=False)
        assert a.overall_score == b.overall_score
        assert a.components == b.components

    def test_store_and_versioning(self, db_session):
        job = _one_job(db_session, source_job_id="q-5")
        row = db_session.scalar(
            select(JobQualityScore).where(JobQualityScore.job_id == job.id)
        )
        assert row is not None
        assert row.scoring_version == "v1"
        assert 0 <= row.overall_score <= 100
        # recalculate must update, not duplicate (unique job+version)
        job_quality_service.calculate(db_session, job, store=True)
        rows = db_session.scalars(
            select(JobQualityScore).where(JobQualityScore.job_id == job.id)
        ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture
def seeded(client_session):
    client, session = client_session
    job_service.insert_jobs(
        session,
        [
            _build_job(
                "Software Engineer",
                "Acme Corp",
                source_job_id="api-1",
                url="https://x.test/1",
                posted_date=date.today() - timedelta(days=1),
            ),
            _build_job(
                "Backend Engineer",
                "Beta LLC",
                source_job_id="api-2",
                url="https://x.test/2",
                posted_date=date.today() - timedelta(days=60),
            ),
        ],
        source="apify",
    )
    return client, session


class TestJobsApiPhase4:
    def test_list_includes_freshness_and_quality(self, seeded):
        client, session = seeded
        body = client.get("/jobs?limit=100").json()
        assert body["total"] == 2
        for item in body["items"]:
            assert item["freshness"]["status"] in set(freshness_service.AGE_RANGES) | {"UNKNOWN"}
            assert "overall_score" in item["quality"]

    def test_freshness_filter(self, seeded):
        client, session = seeded
        assert client.get("/jobs?freshness=VERY_FRESH").json()["total"] == 1
        assert client.get("/jobs?freshness=STALE").json()["total"] == 1
        assert client.get("/jobs?freshness=UNKNOWN").json()["total"] == 0

    def test_freshness_sort_orders_by_posting_date(self, seeded):
        client, session = seeded
        asc = client.get("/jobs?sort=freshness_asc").json()["items"]
        assert asc[0]["posted_date"] < asc[1]["posted_date"]
        desc = client.get("/jobs?sort=freshness_desc").json()["items"]
        assert desc[0]["posted_date"] > desc[1]["posted_date"]

    def test_quality_sort_accepts_option(self, seeded):
        client, session = seeded
        body = client.get("/jobs?sort=quality_desc").json()
        assert body["total"] == 2
        assert client.get("/jobs?sort=quality_asc").json()["total"] == 2

    def test_company_filter(self, seeded):
        client, session = seeded
        assert client.get("/jobs?company=Acme").json()["total"] == 1

    def test_stats_endpoint(self, seeded):
        client, session = seeded
        body = client.get("/jobs/stats").json()
        assert body["total"] == 2
        assert body["freshness_counts"]["very_fresh"] == 1
        assert body["freshness_counts"]["stale"] == 1
        assert isinstance(body["avg_quality"], int)
        assert len(body["top_companies"]) >= 1

    def test_detail_is_enriched(self, seeded):
        client, session = seeded
        items = client.get("/jobs?limit=100").json()["items"]
        acme = next(item for item in items if item["company"] == "Acme Corp")
        detail = client.get(f"/jobs/{acme['id']}").json()
        assert detail["freshness"]["status"] == "VERY_FRESH"
        assert detail["quality"]["overall_score"] is not None
        assert detail["company_info"]["display_name"] == "Acme Corp"
        assert [e["event_type"] for e in detail["recent_events"]] == ["DISCOVERED"]

    def test_bad_sort_rejected(self, seeded):
        client, session = seeded
        assert client.get("/jobs?sort=bogus").status_code == 422

    def test_bad_freshness_rejected(self, seeded):
        client, session = seeded
        assert client.get("/jobs?freshness=meh").status_code == 422


class TestCompaniesApi:
    def test_list_and_detail(self, seeded):
        client, session = seeded
        listings = client.get("/companies").json()
        assert listings["total"] >= 2
        names = {item["display_name"] for item in listings["items"]}
        assert "Acme Corp" in names

        acme = next(item for item in listings["items"] if item["display_name"] == "Acme Corp")
        detail = client.get(f"/companies/{acme['id']}")
        assert detail.status_code == 200
        assert detail.json()["active_job_count"] == 1

    def test_missing_company_404(self, seeded):
        client, session = seeded
        assert client.get("/companies/999999").status_code == 404
