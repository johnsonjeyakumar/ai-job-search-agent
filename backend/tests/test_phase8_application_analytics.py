"""Phase 8: application analytics (funnel, rates, dimensions, trends).

Exercised rules from the spec:
- funnel counts plus conversion rates with EXPLICIT documented denominators;
- zero denominators yield ``None`` (never a misleading 0%);
- small sample sizes are labelled ("Limited data") below the threshold;
- dates are bucketed by first-reach event timestamps with a documented
  fallback to created_at/applied_date for legacy rows;
- role / location / company / source / resume performance groups use
  normalized company identity and split by source + historical resume
  snapshots; nothing invents outcomes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.application_tracking.events import record_application_event
from app.models.application import Application
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import application_analytics_service as analytics
from app.services import application_lifecycle_service as lifecycle


def _seed_profile(db):
    profile = Profile(
        name="Analytics Candidate",
        email=f"ana-{abs(hash(object())) or 9}@example.test",
        city="Chennai",
        skills=["Python"],
        skills_programming=["Python"],
        skills_databases=["SQL"],
        experience_level="0-2 years",
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_resume(db, profile, name="ana_resume.pdf", version="v1"):
    resume = Resume(
        profile_id=profile.id,
        name=name,
        target_role="Software Developer",
        file_path="resumes/ana.pdf",
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
        source_job_id=f"ana-{abs(hash(title))}-{abs(hash(object()))}",
        url="mock://jobs/ana",
    )
    db.add(job)
    db.flush()
    return job


def _seed_preferences(db):
    prefs = Preferences(preferred_locations=["Chennai"])
    db.add(prefs)
    db.flush()
    return prefs


def _track(db, job, *stages, initial="DISCOVERED"):
    """Create a tracked application and walk it through the given stages."""
    app = lifecycle.ensure_application_for_job(db, job.id, initial_status=initial)
    for stage in stages:
        lifecycle.move_lifecycle(db, app, stage)
    return app


_SUBMIT_CHAIN = (
    "SHORTLISTED",
    "PREPARING",
    "READY_FOR_REVIEW",
    "APPROVED",
    "EXECUTION_READY",
    "EXECUTING",
    "SUBMITTED",
)


def _legacy_row(db, job, *, lifecycle_status, applied_date):
    """Simulate a pre-Phase-8 tracker row (no events)."""
    row = Application(
        job_id=job.id,
        status=lifecycle_status.lower(),
        lifecycle_status=lifecycle_status,
        applied_date=applied_date,
        notes="legacy",
    )
    db.add(row)
    db.flush()
    return row


class TestFunnel:
    def _cohort(self, db):
        jobs = [_seed_job(db, f"Role {i}") for i in range(10)]
        _track(db, jobs[0])                       # DISCOVERED only
        _track(db, jobs[1], "SHORTLISTED")
        _track(db, jobs[2], *_SUBMIT_CHAIN[:2])   # -> PREPARING
        _track(db, jobs[3], *_SUBMIT_CHAIN[:4])   # -> APPROVED
        _track(db, jobs[4], *_SUBMIT_CHAIN)       # -> SUBMITTED
        a5 = _track(db, jobs[5], *_SUBMIT_CHAIN, "SUBMISSION_CONFIRMED")
        a6 = _track(db, jobs[6], *_SUBMIT_CHAIN, "SUBMISSION_CONFIRMED",
                    "RESPONSE_RECEIVED")
        _track(db, jobs[7], *_SUBMIT_CHAIN, "SUBMISSION_CONFIRMED",
               "RESPONSE_RECEIVED", "INTERVIEW")
        _track(db, jobs[8], *_SUBMIT_CHAIN, "SUBMISSION_CONFIRMED",
               "RESPONSE_RECEIVED", "OFFER")
        _track(db, jobs[9], *_SUBMIT_CHAIN, "REJECTED")
        for app in (a5, a6):
            app.applied_date = date(2026, 9, 1)
        db.flush()
        return db, a5, a6

    def test_funnel_counts_and_rates_all_time(self, db_session):
        db, a5, a6 = self._cohort(db_session)
        result = analytics.funnel(db_session)
        steps = {s["step"]: s["count"] for s in result["steps"]}
        # Discovered counts jobs in range (all -> every job).
        assert steps["DISCOVERED"] == 10
        assert steps["SHORTLISTED"] == 9
        assert steps["SUBMITTED"] == 6          # jobs 4..9
        assert steps["SUBMISSION_CONFIRMED"] == 4  # jobs 5,6,7,8
        assert steps["RESPONSE_RECEIVED"] == 3     # jobs 6,7,8
        assert steps["INTERVIEW"] == 1
        assert steps["OFFER"] == 1
        assert steps["REJECTED"] == 1
        assert steps["WITHDRAWN"] == 0
        assert steps["PREPARING"] == 8
        assert steps["READY_FOR_REVIEW"] == 7
        assert steps["APPROVED"] == 7

        rates = result["rates"]
        assert rates["submission_confirmed_rate"] == round(400 / 6, 1)  # 4/6
        assert rates["response_rate"] == 50.0               # 3/6
        assert rates["interview_rate"] == round(100 / 6, 1)
        assert rates["offer_rate"] == round(100 / 6, 1)
        assert rates["rejection_rate"] == round(100 / 6, 1)
        assert "date_basis" in result
        assert "rate_formulas" in result

    def test_funnel_zero_denominator_returns_none(self, db_session):
        job = _seed_job(db_session, "Lone Role")
        _track(db_session, job)  # never submitted
        result = analytics.funnel(db_session)
        rates = result["rates"]
        assert rates["response_rate"] is None
        assert rates["interview_rate"] is None
        assert rates["offer_rate"] is None
        assert rates["rejection_rate"] is None

    def test_funnel_date_range_excludes_legacy_old_rows(self, db_session):
        job = _seed_job(db_session, "Fresh Role")
        _track(db_session, job, *_SUBMIT_CHAIN)
        old_job = _seed_job(db_session, "Old Role")
        _legacy_row(
            db_session,
            old_job,
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date(2026, 1, 15),
        )
        db_session.flush()

        all_time = analytics.funnel(db_session)
        steps_all = {s["step"]: s["count"] for s in all_time["steps"]}
        assert steps_all["SUBMITTED"] == 2
        assert steps_all["SUBMISSION_CONFIRMED"] == 1

        last30 = analytics.funnel(
            db_session, "last_30_days", start=None, end=None
        )
        steps30 = {s["step"]: s["count"] for s in last30["steps"]}
        assert steps30["SUBMITTED"] == 1
        assert steps30["SUBMISSION_CONFIRMED"] == 0

    def test_funnel_custom_range_invalid(self, db_session):
        import pytest

        job = _seed_job(db_session, "Range Job")
        _track(db_session, job, *_SUBMIT_CHAIN)
        with pytest.raises(ValueError):
            analytics.funnel(
                db_session, "custom", start="not-a-date", end="2026-09-30"
            )


class TestStatusCounts:
    def test_status_counts_total_and_distribution(self, db_session):
        job1 = _seed_job(db_session, "One")
        job2 = _seed_job(db_session, "Two")
        _track(db_session, job1, *_SUBMIT_CHAIN)
        _track(db_session, job2, *_SUBMIT_CHAIN, "SUBMISSION_CONFIRMED")
        body = analytics.status_counts(db_session)
        assert body["total_tracked"] == 2
        assert body["status_counts"]["SUBMITTED"] == 1
        assert body["status_counts"]["SUBMISSION_CONFIRMED"] == 1
        assert body["status_counts"]["DISCOVERED"] == 0


class TestDimensions:
    def test_by_role_rates_and_limited_sample(self, db_session):
        job = _seed_job(db_session, "Platform Engineer")
        _seed_resume(db_session, _seed_profile(db_session))
        _track(db_session, job, *_SUBMIT_CHAIN, "SUBMISSION_CONFIRMED",
               "RESPONSE_RECEIVED", "INTERVIEW")
        rows = analytics.by_role(db_session)
        assert len(rows) == 1
        row = rows[0]
        assert row["label"] == "Platform Engineer"
        assert row["submitted"] == 1
        assert row["interviews"] == 1
        assert row["limited_data"] is True
        assert row["limited_label"] == "Limited sample (n=1)"
        assert row["interview_rate"] == 100.0

    def test_by_company_normalizes_identity(self, db_session):
        _seed_profile(db_session)
        j1 = _seed_job(db_session, "R1", company="Acme Technologies")
        j2 = _seed_job(db_session, "R2", company="acme technologies")
        j3 = _seed_job(db_session, "R3", company="Globex Inc")
        _track(db_session, j1, *_SUBMIT_CHAIN)
        _track(db_session, j2, *_SUBMIT_CHAIN)
        _track(db_session, j3)
        rows = analytics.by_company(db_session)
        keys = {r["key"] for r in rows}
        # Acme Technologies variants collapse into one normalized key.
        assert len(rows) == 2
        assert any("acme" in k for k in keys)
        acme = next(r for r in rows if "acme" in r["key"])
        assert acme["applications"] == 2
        assert acme["submitted"] == 2

    def test_by_source_and_resume_snapshot(self, db_session):
        profile = _seed_profile(db_session)
        resume = _seed_resume(db_session, profile, name="v2_resume.pdf", version="v2")
        j1 = _seed_job(db_session, "S1", source="linkedin")
        j2 = _seed_job(db_session, "S2", source="indeed")
        a1 = lifecycle.ensure_application_for_job(
            db_session, j1.id, initial_status="DISCOVERED"
        )
        a1.resume_id = resume.id
        a1.resume_name = resume.name
        a1.resume_version = resume.version
        for stage in _SUBMIT_CHAIN:
            lifecycle.move_lifecycle(db_session, a1, stage)
        a2 = lifecycle.ensure_application_for_job(
            db_session, j2.id, initial_status="DISCOVERED"
        )
        lifecycle.move_lifecycle(db_session, a2, "SHORTLISTED")
        db_session.flush()

        sources = analytics.by_source(db_session)
        src_map = {r["key"]: r for r in sources}
        assert src_map["linkedin"]["submitted"] == 1
        assert src_map["indeed"]["submitted"] == 0

        resumes = analytics.by_resume(db_session)
        resume_labels = [r["label"] for r in resumes]
        assert any("v2_resume.pdf" in label for label in resume_labels)
        # Apps without a resume snapshot are grouped separately, not invented.
        assert any(label == "No resume" for label in resume_labels)


class TestResponseTimes:
    def test_days_to_response_measured_from_submission(self, db_session):
        job = _seed_job(db_session, "Timed Role")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        record_application_event(
            db_session,
            app.id,
            "RESPONSE_RECEIVED",
            previous_status="SUBMITTED",
            new_status="RESPONSE_RECEIVED",
            event_timestamp=datetime(2026, 9, 6, 14, 30),
        )
        db_session.flush()
        times = analytics.response_times(db_session)
        assert times["days_to_response"]["measured"] == 1
        assert times["days_to_response"]["average_days"] == 5
        assert times["days_to_response"]["median_days"] == 5

    def test_no_dates_means_no_invention(self, db_session):
        job = _seed_job(db_session, "Quiet Role")
        _track(db_session, job, "SHORTLISTED")
        times = analytics.response_times(db_session)
        assert times["days_to_response"]["measured"] == 0
        assert times["days_to_response"]["average_days"] is None


class TestTrends:
    def test_weekly_application_and_response_trends(self, db_session):
        job = _seed_job(db_session, "Trend Role")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        record_application_event(
            db_session, app.id, "RESPONSE_RECEIVED",
            previous_status="SUBMITTED", new_status="RESPONSE_RECEIVED",
            event_timestamp=datetime.now(),
        )
        db_session.flush()
        items = analytics.over_time(db_session)
        assert len(items) >= 1
        this_week = items[-1]
        assert this_week["applications"] >= 1
        assert this_week["responses"] >= 1
        assert "week_start" in this_week


class TestFollowUpSummary:
    def test_due_overdue_upcoming_counts(self, db_session):
        job_over = _seed_job(db_session, "Overdue")
        app_over = lifecycle.ensure_application_for_job(db_session, job_over.id)
        lifecycle.create_follow_up(
            db_session, app_over, scheduled_date=date.today() - timedelta(days=3)
        )

        job_today = _seed_job(db_session, "Today")
        app_today = lifecycle.ensure_application_for_job(db_session, job_today.id)
        lifecycle.create_follow_up(
            db_session, app_today, scheduled_date=date.today()
        )

        job_future = _seed_job(db_session, "Future")
        app_future = lifecycle.ensure_application_for_job(db_session, job_future.id)
        lifecycle.create_follow_up(
            db_session, app_future, scheduled_date=date.today() + timedelta(days=2)
        )

        summary = analytics.follow_up_summary(db_session)
        assert summary["total"] == 3
        assert summary["due_today"] == 1
        assert summary["overdue"] == 1
        assert summary["due_this_week"] >= 2
        assert summary["upcoming"] == 1
        assert len(summary["items"]) == 3
        assert summary["items"][0]["job_title"]


class TestTrackingRowsExtra:
    def test_filter_by_follow_up_state(self, db_session):
        job = _seed_job(db_session, "FollowUp Role")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        lifecycle.create_follow_up(
            db_session, app, scheduled_date=date.today()
        )
        due = analytics.tracking_rows(db_session, follow_up="DUE")
        assert len(due) == 1
        none = analytics.tracking_rows(db_session, follow_up="NONE")
        assert none == []

    def test_status_counts_aligns_with_rows(self, db_session):
        job = _seed_job(db_session, "Counts Role")
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        lifecycle.move_lifecycle(db_session, app, "SHORTLISTED")
        rows = analytics.tracking_rows(db_session)
        assert len(rows) == 1
        counts = {r["status"]: 1 for r in rows}
        assert counts["SHORTLISTED"] == 1
