"""Phase 9: follow-up engine (priority/reason/trigger/skip/restore) + API.

Exercised rules from the spec:
- follow-ups carry a priority, a reason vocabulary and a trigger snapshot, and
  stay deterministic (never LLM-derived);
- DUE/OVERDUE/RESCHEDULED/SCHEDULED/SKIPPED are derived at read time while the
  stored status vocabulary only gains SKIPPED;
- an interview schedules exactly one high-priority thank-you follow-up (per
  interview record) offset by ``interview_follow_up_days``;
- skip/restore are first-class actions with immutable timeline events;
- the follow-up API exposes filters (status/priority/due/overdue/company/date)
  and per-follow-up detail; no follow-ups are created for applications that are
  rejected/withdrawn/expired/cancelled/offer or that already have a response.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.application_tracking.events import timeline
from app.models.application import FollowUp
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import application_analytics_service as analytics
from app.services import application_lifecycle_service as lifecycle


def _seed_profile(db):
    profile = Profile(
        name="Follow-up Candidate",
        email=f"fu-{abs(hash(object())) or 7}@example.test",
        city="Chennai",
        skills=["Python", "SQL"],
        skills_programming=["Python"],
        skills_databases=["SQL"],
        experience_level="0-2 years",
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_resume(db, profile, name="fu_resume.pdf", version="v1"):
    resume = Resume(
        profile_id=profile.id,
        name=name,
        target_role="Software Developer",
        file_path="resumes/fu.pdf",
        file_name=name,
        content_type="application/pdf",
        version=version,
    )
    db.add(resume)
    db.flush()
    return resume


def _seed_job(db, title="Software Developer", company="Acme", source="apify"):
    job = Job(
        title=title,
        company=company,
        location="Chennai",
        remote_type="onsite",
        source=source,
        source_job_id=f"p9-{abs(hash(title))}-{abs(hash(object()))}",
        url="mock://careers/fu",
    )
    db.add(job)
    db.flush()
    return job


def _seed_preferences(db, interval=7, interview_days=1):
    prefs = Preferences(
        preferred_locations=["Chennai"],
        target_roles=["Software Developer"],
        follow_up_interval_days=interval,
        interview_follow_up_days=interview_days,
    )
    db.add(prefs)
    db.flush()
    return prefs


def _submit(db, app, *, confirmed=False):
    for stage in (
        "PREPARING",
        "READY_FOR_REVIEW",
        "APPROVED",
        "EXECUTION_READY",
        "EXECUTING",
        "SUBMITTED",
    ):
        lifecycle.move_lifecycle(db, app, stage)
    if confirmed:
        lifecycle.move_lifecycle(db, app, "SUBMISSION_CONFIRMED")
    return app


def _fu(db, app_id):
    return db.scalar(
        select(FollowUp).where(FollowUp.application_id == app_id).order_by(FollowUp.id)
    )


def _seed_app_with_fu_date(db, when):
    """Fresh application with its own follow-up scheduled on ``when``."""
    job = _seed_job(db)
    app = lifecycle.ensure_application_for_job(db, job.id)
    fu = lifecycle.create_follow_up(db, app, scheduled_date=when)
    assert fu is not None
    return fu


class TestFollowUpEngine:
    def test_defaults_reason_and_priority(self, db_session):
        _seed_preferences(db_session)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit(db_session, app)
        fu = _fu(db_session, app.id)
        assert fu.priority == "MEDIUM"
        assert fu.reason == "SUBMISSION_FOLLOW_UP"
        assert fu.trigger_status == "SUBMITTED"
        assert fu.trigger_key == f"app:{app.id}:SUBMISSION_FOLLOW_UP:SUBMITTED"
        assert fu.status == "PENDING"

    def test_invalid_reason_and_priority_rejected(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        with pytest_lifecycle_raises():
            lifecycle.create_follow_up(db_session, app, reason="MADE_UP")
        with pytest_lifecycle_raises():
            lifecycle.create_follow_up(db_session, app, priority="URGENT")

    def test_no_follow_up_after_offer_or_response(self, db_session):
        _seed_preferences(db_session)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        lifecycle.move_lifecycle(db_session, app, "REJECTED")
        assert lifecycle.create_follow_up(db_session, app) is None

        job2 = _seed_job(db_session, title="Responded", company="Globex")
        app2 = lifecycle.ensure_application_for_job(db_session, job2.id)
        _submit(db_session, app2)
        lifecycle.record_response(
            db_session, app2, category="RECRUITER_CONTACT", received_at=date(2026, 9, 3)
        )
        assert lifecycle.create_follow_up(db_session, app2) is None

    def test_interview_schedules_thank_you_once_per_record(self, db_session):
        _seed_preferences(db_session, interview_days=2)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit(db_session, app)
        lifecycle.record_interview(
            db_session, app, interview_date=date(2026, 9, 10)
        )
        iv2 = lifecycle.record_interview(
            db_session, app, interview_date=date(2026, 9, 17)
        )
        thank_you = [
            f for f in analytics.follow_up_summary(db_session)["items"]
            if f["application_id"] == app.id and f["reason"] == "INTERVIEW_THANK_YOU"
        ]
        assert len(thank_you) == 2  # one per interview record
        assert all(t["priority"] == "HIGH" for t in thank_you)
        by_date = {t["scheduled_date"]: t for t in thank_you}
        assert by_date[date(2026, 9, 12).isoformat()]["trigger_status"] == "INTERVIEW"
        assert by_date[date(2026, 9, 19).isoformat()]["trigger_key"].endswith(str(iv2.id))
        # submission follow-up is still present alongside both thank-yous
        keys = {t["trigger_key"] for t in analytics.follow_up_summary(db_session)["items"]
                if t["application_id"] == app.id}
        assert f"app:{app.id}:SUBMISSION_FOLLOW_UP:SUBMITTED" in keys

    def test_skip_and_restore(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        fu = lifecycle.create_follow_up(
            db_session, app, scheduled_date=date(2026, 9, 1)
        )
        lifecycle.skip_follow_up(db_session, fu, notes="No action needed.")
        assert fu.status == "SKIPPED"
        assert fu.skipped_at is not None
        types = [e.event_type for e in timeline(db_session, app.id)]
        assert "FOLLOW_UP_SKIPPED" in types

        lifecycle.restore_follow_up(db_session, fu)
        assert fu.status == "PENDING"
        assert fu.skipped_at is None
        # restore bumped a past scheduled date to the real today
        assert fu.scheduled_date == date.today()
        assert lifecycle.follow_up_lifecycle_state(fu, today=date.today()) == "DUE"
        types = [e.event_type for e in timeline(db_session, app.id)]
        assert "FOLLOW_UP_RESTORED" in types

    def test_skip_completed_or_restore_active_rejected(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        fu = lifecycle.create_follow_up(
            db_session, app, scheduled_date=date(2026, 9, 1)
        )
        with pytest_lifecycle_raises():
            lifecycle.restore_follow_up(db_session, fu)  # already active
        lifecycle.complete_follow_up(db_session, fu)
        with pytest_lifecycle_raises():
            lifecycle.skip_follow_up(db_session, fu)  # already finished

    def test_lifecycle_state_derivation(self, db_session):
        today = date(2026, 9, 1)
        future = _seed_app_with_fu_date(db_session, today + timedelta(days=19))
        due = _seed_app_with_fu_date(db_session, today)
        past = _seed_app_with_fu_date(db_session, today - timedelta(days=12))
        assert lifecycle.follow_up_lifecycle_state(future, today=today) == "SCHEDULED"
        assert lifecycle.follow_up_lifecycle_state(due, today=today) == "DUE"
        assert lifecycle.follow_up_lifecycle_state(past, today=today) == "OVERDUE"

        resched_job = _seed_job(db_session, title="Reschedule target")
        resched_app = lifecycle.ensure_application_for_job(db_session, resched_job.id)
        reschedule_fu = lifecycle.create_follow_up(
            db_session, resched_app, scheduled_date=today + timedelta(days=30)
        )
        lifecycle.reschedule_follow_up(
            db_session, reschedule_fu, scheduled_date=today + timedelta(days=29)
        )
        assert lifecycle.follow_up_lifecycle_state(
            reschedule_fu, rescheduled=True, today=today
        ) == "RESCHEDULED"
        lifecycle.complete_follow_up(db_session, past)
        assert lifecycle.follow_up_lifecycle_state(
            past, today=today
        ) == "COMPLETED"


class TestFollowUpAPI:
    def _seed_app_with_fu(self, client, session, *, company="Acme", title="Engineer"):
        job = _seed_job(session, title=title, company=company)
        app = lifecycle.ensure_application_for_job(session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit(session, app)
        fu = _fu(session, app.id)
        client.post(f"/tracking/follow-ups/{fu.id}/reschedule",
                    json={"scheduled_date": "2026-09-02"})
        return app, fu

    def test_detail_and_summary_endpoints(self, client_session):
        client, session = client_session
        _seed_preferences(session)
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit(session, app)
        fu = _fu(session, app.id)

        summary = client.get("/tracking/follow-ups/summary")
        assert summary.status_code == 200
        assert summary.json()["total"] == 1
        assert "due_this_week" in summary.json()

        detail = client.get(f"/tracking/follow-ups/{fu.id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["priority"] == "MEDIUM"
        assert body["reason"] == "SUBMISSION_FOLLOW_UP"
        assert body["application_status"] == "SUBMITTED"
        assert body["resume_name"] is None

        missing = client.get("/tracking/follow-ups/999999")
        assert missing.status_code == 404

    def test_skip_and_restore_via_api(self, client_session):
        client, session = client_session
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(session, job.id)
        fu = lifecycle.create_follow_up(
            session, app, scheduled_date=date(2026, 9, 1)
        )
        skipped = client.post(f"/tracking/follow-ups/{fu.id}/skip",
                              json={"notes": "No action needed."})
        assert skipped.status_code == 200, skipped.text
        assert fu.status == "SKIPPED"
        restored = client.post(f"/tracking/follow-ups/{fu.id}/restore")
        assert restored.status_code == 200, restored.text
        assert fu.status == "PENDING"

    def test_filters_on_follow_ups_list(self, client_session):
        client, session = client_session
        _seed_preferences(session)
        job_a = _seed_job(session, title="Acme role", company="Acme")
        job_b = _seed_job(session, title="Globex role", company="Globex")
        a = lifecycle.ensure_application_for_job(session, job_a.id)
        b = lifecycle.ensure_application_for_job(session, job_b.id)
        a.applied_date = date(2026, 9, 1)
        b.applied_date = date(2026, 9, 5)
        _submit(session, a)
        _submit(session, b)
        fa = _fu(session, a.id)
        fb = _fu(session, b.id)
        today = date.today()
        # fa is overdue (past date); fb is due (today)
        client.post(f"/tracking/follow-ups/{fa.id}/reschedule",
                    json={"scheduled_date": (today - timedelta(days=30)).isoformat()})
        client.post(f"/tracking/follow-ups/{fb.id}/reschedule",
                    json={"scheduled_date": today.isoformat()})

        resp = client.get("/tracking/follow-ups", params={"overdue": "true"})
        assert resp.status_code == 200, resp.text
        ids = [i["id"] for i in resp.json()["items"]]
        assert fa.id in ids
        assert fb.id not in ids

        resp = client.get("/tracking/follow-ups", params={"due": "true"})
        ids = [i["id"] for i in resp.json()["items"]]
        assert fb.id in ids
        assert fa.id not in ids

        resp = client.get("/tracking/follow-ups", params={"priority": "HIGH"})
        assert resp.json()["items"] == []

        resp = client.get("/tracking/follow-ups", params={"company": "Globex"})
        ids = [i["id"] for i in resp.json()["items"]]
        assert ids == [fb.id]

        resp = client.get(
            "/tracking/follow-ups",
            params={
                "from_date": (today - timedelta(days=1)).isoformat(),
                "to_date": (today + timedelta(days=1)).isoformat(),
            },
        )
        ids = [i["id"] for i in resp.json()["items"]]
        assert fb.id in ids and fa.id not in ids

    def test_invalid_status_filter_returns_422(self, client_session):
        client, _session = client_session
        resp = client.get("/tracking/follow-ups", params={"status": "NOPE"})
        assert resp.status_code == 422

    def test_pending_filter_includes_derived_active_states(self, client_session):
        client, session = client_session
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(session, job.id)
        fu = lifecycle.create_follow_up(
            session, app, scheduled_date=date(2026, 9, 1)
        )
        client.post(f"/tracking/follow-ups/{fu.id}/skip")
        resp = client.get("/tracking/follow-ups", params={"status": "PENDING"})
        assert resp.json()["items"] == []
        client.post(f"/tracking/follow-ups/{fu.id}/restore")
        resp = client.get("/tracking/follow-ups", params={"status": "PENDING"})
        assert [i["id"] for i in resp.json()["items"]] == [fu.id]


def pytest_lifecycle_raises():
    import pytest
    return pytest.raises(lifecycle.TrackingError)
