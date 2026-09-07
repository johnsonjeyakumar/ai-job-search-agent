"""Phase 9: resume & job-source analytics, response-time breakdowns, insights.

Exercised rules from the spec:
- resume performance keeps historical snapshots, adds derived rank labels
  (STRONGER SIGNAL / PROMISING / LIMITED DATA / INSUFFICIENT DATA) and supports
  role / location / source / company / date filters;
- ``recommended_resume`` is deterministic and never fabricates a pick when
  historical data is thin;
- source performance splits discovery vs actual submission platforms and
  scores them with explicit, documented weights over verified rates;
- response-time breakdowns and insights only echo verified numbers.
"""
from __future__ import annotations

from datetime import date

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import application_analytics_service as analytics
from app.services import application_lifecycle_service as lifecycle


def _seed_profile(db):
    profile = Profile(
        name="Resume Analyst",
        email=f"rs-{abs(hash(object())) or 9}@example.test",
        city="Chennai",
        skills=["Python"],
        skills_programming=["Python"],
        skills_databases=["SQL"],
        experience_level="0-2 years",
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_resume(db, profile, name="rs_resume.pdf", version="v1"):
    resume = Resume(
        profile_id=profile.id,
        name=name,
        target_role="Software Developer",
        file_path="resumes/rs.pdf",
        file_name=name,
        content_type="application/pdf",
        version=version,
    )
    db.add(resume)
    db.flush()
    return resume


def _seed_job(db, title, company="Acme", source="apify", location="Chennai"):
    job = Job(
        title=title,
        company=company,
        location=location,
        remote_type="onsite",
        source=source,
        source_job_id=f"rs-{abs(hash(title))}-{abs(hash(object()))}",
        url="mock://jobs/rs",
    )
    db.add(job)
    db.flush()
    return job


def _submit_and_respond(db, app, *, respond=True, interview=False):
    for stage in (
        "PREPARING",
        "READY_FOR_REVIEW",
        "APPROVED",
        "EXECUTION_READY",
        "EXECUTING",
        "SUBMITTED",
    ):
        lifecycle.move_lifecycle(db, app, stage)
    if respond:
        lifecycle.move_lifecycle(db, app, "SUBMISSION_CONFIRMED")
        if interview:
            lifecycle.move_lifecycle(db, app, "RESPONSE_RECEIVED")
            lifecycle.move_lifecycle(db, app, "INTERVIEW")
        else:
            lifecycle.move_lifecycle(db, app, "RESPONSE_RECEIVED")
    return app


class TestResumePerformance:
    def test_rank_labels_and_filters(self, db_session):
        profile = _seed_profile(db_session)
        r1 = _seed_resume(db_session, profile, name="rs_a.pdf", version="v2")
        _seed_resume(db_session, profile, name="rs_b.pdf", version="v1")

        job = _seed_job(db_session, "Software Developer", company="Acme", source="apify")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.resume_id = r1.id
        app.resume_name = r1.name
        app.resume_version = r1.version
        app.applied_date = date(2026, 9, 1)
        _submit_and_respond(db_session, app)

        rows = analytics.resume_performance(db_session)
        assert len(rows) == 1
        row = rows[0]
        assert "rs_a.pdf" in row["label"]
        assert row["submitted"] == 1
        assert row["rank_label"] == "LIMITED DATA"  # below threshold

        filtered = analytics.resume_performance(db_session, role="Software Developer")
        assert len(filtered) == 1
        other = analytics.resume_performance(db_session,
                                             role="Something else")
        assert other == []

    def test_no_resume_and_empty_groups_insufficient(self, db_session):
        job = _seed_job(db_session, "Data Engineer")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit_and_respond(db_session, app)
        rows = analytics.resume_performance(db_session)
        labels = [r["label"] for r in rows]
        assert "No resume" in labels
        for row in rows:
            if row["submitted"] == 0:
                assert row["rank_label"] == "INSUFFICIENT DATA"
                assert row["composite_score"] == 0.0


class TestRecommendedResume:
    def test_no_data_returns_message(self, db_session):
        result = analytics.recommended_resume(db_session, role="Engineer")
        assert result["candidate"] is None
        assert result["message"] == "Not enough historical data to recommend a resume."

    def test_chooses_best_qualified_resume(self, db_session):
        profile = _seed_profile(db_session)
        good = _seed_resume(db_session, profile, name="good.pdf", version="v1")
        # 2 submissions -> below threshold, so qualification can't be reached
        # with the small-sample guard; instead build 5 submissions of `good`
        submitted = 0
        for i in range(6):
            job = _seed_job(db_session, f"Role {i}", company="Acme", source="apify")
            app = lifecycle.ensure_application_for_job(db_session, job.id)
            app.resume_id = good.id
            app.resume_name = good.name
            app.resume_version = good.version
            app.applied_date = date(2026, 9, 1 + i)
            _submit_and_respond(db_session, app, respond=(i < 5), interview=True)
            submitted += 1

        result = analytics.recommended_resume(db_session, role="Role")
        assert result["candidate"] is not None
        assert result["candidate"]["submitted"] >= analytics.SMALL_SAMPLE_THRESHOLD
        assert result["recommended_resume_id"] == result["candidate"]["key"]
        # deterministic: same call twice yields the same pick
        repeat = analytics.recommended_resume(db_session, role="Role")
        assert repeat["candidate"]["key"] == result["candidate"]["key"]


class TestSourcePerformance:
    def test_insufficient_when_nothing_submitted(self, db_session):
        job = _seed_job(db_session, "Role", company="Acme", source="indeed")
        lifecycle.ensure_application_for_job(db_session, job.id, initial_status="DISCOVERED")
        perf = analytics.source_performance(db_session)
        discovery = {s["label"]: s for s in perf["discovery"]}
        row = discovery["indeed"]
        assert row["source_quality"]["label"] == "INSUFFICIENT DATA"
        assert row["source_quality"]["score"] is None

    def test_explicit_documented_weights(self, db_session):
        assert abs(sum(analytics.SOURCE_QUALITY_WEIGHTS.values()) - 1.0) < 1e-9
        assert analytics.SOURCE_QUALITY_WEIGHTS["response_rate"] == 0.40
        assert "score =" in analytics.SOURCE_QUALITY_BASIS

    def test_submission_source_bucket_from_real_platform_only(self, db_session):
        job = _seed_job(db_session, "Role", company="Acme", source="apify")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.application_source = "linkedin"  # recorded from an execution platform
        app.applied_date = date(2026, 9, 1)
        _submit_and_respond(db_session, app)
        perf = analytics.source_performance(db_session)
        submission = {s["label"]: s for s in perf["submission"]}
        assert "linkedin" in submission
        assert "No submission source" not in submission


class TestResponseTimeBreakdowns:
    def test_overall_and_role_bucket(self, db_session):
        job_a = _seed_job(db_session, "Engineer A", company="Acme", source="apify")
        job_b = _seed_job(db_session, "Engineer B", company="Acme", source="apify")
        a = lifecycle.ensure_application_for_job(db_session, job_a.id)
        b = lifecycle.ensure_application_for_job(db_session, job_b.id)
        a.applied_date = date(2026, 9, 1)
        b.applied_date = date(2026, 9, 1)
        _submit_and_respond(db_session, a, respond=True)
        _submit_and_respond(db_session, b, respond=True)

        out = analytics.response_time_breakdowns(db_session)
        assert out["overall"]["measured"] == 2
        assert out["overall"]["median_days"] >= 0
        role_bucket = {r["label"]: r for r in out["dimensions"]["role"]}
        assert "Engineer A" in role_bucket
        assert role_bucket["Engineer A"]["measured"] == 1

    def test_no_responses_yield_zero_measured(self, db_session):
        job = _seed_job(db_session, "Engineer")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit_and_respond(db_session, app, respond=False)
        out = analytics.response_time_breakdowns(db_session)
        assert out["overall"]["measured"] == 0
        assert out["overall"]["median_days"] is None


class TestInsights:
    def test_no_data_message(self, db_session):
        out = analytics.insights(db_session)
        assert [i["key"] for i in out["items"]] == ["no_data"]

    def test_with_data_echoes_verified_metrics(self, db_session):
        job = _seed_job(db_session, "Engineer", company="Acme", source="apify")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit_and_respond(db_session, app, respond=True, interview=True)
        out = analytics.insights(db_session)
        keys = [i["key"] for i in out["items"]]
        assert "no_data" not in keys
        assert any(k in keys for k in ("response_speed",))
        for item in out["items"]:
            assert "metrics" in item and item["metrics"]  # evidence always shown
        repeat = analytics.insights(db_session)
        assert repeat == out  # deterministic
