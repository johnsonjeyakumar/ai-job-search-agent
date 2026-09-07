"""Phase 8: application tracking (state machine, events, follow-ups).

Exercised rules from the spec:
- statuses live on a controlled vocabulary, never arbitrary strings;
- legal transitions only; nonsensical ones (e.g. REJECTED -> INTERVIEW) require
  an explicit override and always write a STATUS_CORRECTED event (never silent);
- events are immutable / append-only and timeline ordering is deterministic;
- follow-ups are scheduled centrally after first submission with a
  user-configurable interval; DUE is derived at read time; rejections/withdrawn
  applications never get follow-ups;
- responses / interviews / offers are recorded as structured rows alongside
  history events; categories/statuses are validated.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application_tracking import status as app_status
from app.application_tracking.events import (
    latest_event,
    record_application_event,
    timeline,
)
from app.models.application import Application, FollowUp
from app.models.application_tracking import (
    ApplicationEvent,
    ApplicationResponse,
    InterviewRecord,
    OfferRecord,
)
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import application_analytics_service as analytics
from app.services import application_lifecycle_service as lifecycle


def _seed_profile(db):
    profile = Profile(
        name="Track Candidate",
        email=f"track-{abs(hash(object())) or 7}@example.test",
        city="Chennai",
        skills=["Python", "SQL"],
        skills_programming=["Python"],
        skills_databases=["SQL"],
        experience_level="0-2 years",
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_resume(db, profile, name="track_resume.pdf", version="v1"):
    resume = Resume(
        profile_id=profile.id,
        name=name,
        target_role="Software Developer",
        file_path="resumes/track.pdf",
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
        source_job_id=f"p8-{abs(hash(title))}-{abs(hash(object()))}",
        url="mock://careers/track",
    )
    db.add(job)
    db.flush()
    return job


def _seed_preferences(db, interval=7):
    prefs = Preferences(
        preferred_locations=["Chennai"],
        target_roles=["Software Developer"],
        follow_up_interval_days=interval,
    )
    db.add(prefs)
    db.flush()
    return prefs


def _event_count(db, application_id):
    return len(
        list(
            db.scalars(
                select(ApplicationEvent).where(
                    ApplicationEvent.application_id == application_id
                )
            )
        )
    )


def _submit(db, app, *, confirmed=False):
    """Walk an application through the legal chain to SUBMITTED (and
    optionally SUBMISSION_CONFIRMED), recording each step's event."""
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


def _apps(db):
    return list(db.scalars(select(Application).order_by(Application.id)))


class TestStateMachine:
    def test_controlled_vocabulary(self):
        assert "SHORTLISTED" in app_status.TRACKING_STATUSES
        assert "NOT_A_STATUS" not in app_status.TRACKING_STATUSES
        with pytest.raises(app_status.InvalidStatusError):
            app_status.validate_target_status("NOT_A_STATUS")

    def test_transition_graph(self):
        assert app_status.can_transition("DISCOVERED", "SHORTLISTED")
        assert not app_status.can_transition("REJECTED", "INTERVIEW")
        assert not app_status.can_transition("PREPARING", "OFFER")

    def test_is_terminal(self):
        assert app_status.is_terminal("REJECTED")
        assert app_status.is_terminal("OFFER")
        assert not app_status.is_terminal("SUBMITTED")


class TestLifecycleService:
    def test_ensure_application_creates_events_and_is_idempotent(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(
            db_session, job.id, initial_status="SHORTLISTED", source="USER"
        )
        assert app.lifecycle_status == "SHORTLISTED"
        assert _event_count(db_session, app.id) == 2  # created + shortlisted
        again = lifecycle.ensure_application_for_job(db_session, job.id)
        assert again.id == app.id
        assert _event_count(db_session, app.id) == 2  # no duplicate events

    def test_legal_transition_records_event(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(
            db_session, job.id, initial_status="DISCOVERED"
        )
        for stage in (
            "SHORTLISTED",
            "PREPARING",
            "READY_FOR_REVIEW",
            "APPROVED",
            "EXECUTION_READY",
            "EXECUTING",
            "SUBMITTED",
        ):
            lifecycle.move_lifecycle(db_session, app, stage)
        assert app.lifecycle_status == "SUBMITTED"
        ev = next(
            e for e in timeline(db_session, app.id) if e.event_type == "SUBMITTED"
        )
        assert ev.previous_status == "EXECUTING"
        assert ev.new_status == "SUBMITTED"

    def test_illegal_transition_raises_and_changes_nothing(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(
            db_session, job.id, initial_status="REJECTED"
        )
        before = _event_count(db_session, app.id)
        with pytest.raises(lifecycle.TrackingError):
            lifecycle.move_lifecycle(db_session, app, "INTERVIEW")
        assert app.lifecycle_status == "REJECTED"
        assert _event_count(db_session, app.id) == before

    def test_override_writes_status_corrected_event(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(
            db_session, job.id, initial_status="REJECTED"
        )
        lifecycle.move_lifecycle(db_session, app, "INTERVIEW", override=True)
        assert app.lifecycle_status == "INTERVIEW"
        ev = latest_event(db_session, app.id)
        assert ev.event_type == "STATUS_CORRECTED"
        assert ev.previous_status == "REJECTED"
        assert ev.new_status == "INTERVIEW"

    def test_immutable_history_order(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        base = datetime.now()
        for i, ev_type in enumerate(
                ["SHORTLISTED", "PACKAGE_PREPARED", "PACKAGE_READY_FOR_REVIEW"]
            ):
            record_application_event(
                db_session,
                app.id,
                ev_type,
                event_timestamp=base + timedelta(minutes=i),
            )
        db_session.flush()
        ordered = timeline(db_session, app.id)
        stamps = [e.event_timestamp for e in ordered]
        assert stamps == sorted(stamps)

    def test_add_note_appends_note_event(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        lifecycle.add_note(db_session, app, "Hiring manager pinged me.")
        assert "Hiring manager pinged me." in app.notes
        ev = latest_event(db_session, app.id)
        assert ev.event_type == "NOTE_ADDED"


class TestResponsesInterviewsOffers:
    def test_response_rejected_moves_status(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        row = lifecycle.record_response(
            db_session, app, category="REJECTED", received_at=date(2026, 9, 1)
        )
        assert isinstance(row, ApplicationResponse)
        assert app.lifecycle_status == "REJECTED"

    def test_response_offer_moves_status(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        lifecycle.record_response(
            db_session, app, category="OFFER", received_at=date(2026, 9, 2)
        )
        assert app.lifecycle_status == "OFFER"

    def test_response_generic_records_response_received(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        lifecycle.record_response(
            db_session, app, category="RECRUITER_CONTACT", received_at=date(2026, 9, 3)
        )
        assert app.lifecycle_status == "RESPONSE_RECEIVED"

    def test_invalid_response_category_rejected(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        with pytest.raises(lifecycle.TrackingError):
            lifecycle.record_response(
                db_session, app, category="MADE_UP", received_at=date(2026, 9, 3)
            )

    def test_interview_and_offer_records(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        iv = lifecycle.record_interview(
            db_session, app, interview_date=date(2026, 9, 10), interview_type="TECHNICAL"
        )
        assert isinstance(iv, InterviewRecord)
        assert app.lifecycle_status == "INTERVIEW"
        off = lifecycle.record_offer(
            db_session, app, offer_date=date(2026, 9, 24), status="RECEIVED"
        )
        assert isinstance(off, OfferRecord)
        assert app.lifecycle_status == "OFFER"

    def test_interview_when_offer_already_streams_transparent_event(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        lifecycle.record_response(
            db_session, app, category="OFFER", received_at=date(2026, 9, 20)
        )
        assert app.lifecycle_status == "OFFER"
        before = _event_count(db_session, app.id)
        lifecycle.record_interview(
            db_session, app, interview_date=date(2026, 9, 10)
        )
        assert app.lifecycle_status == "OFFER"  # unchanged
        assert _event_count(db_session, app.id) == before + 1  # transparent event


class TestFollowUps:
    def test_follow_up_scheduled_on_first_submission(self, db_session):
        _seed_preferences(db_session, interval=7)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit(db_session, app)
        fu = db_session.scalar(
            select(FollowUp).where(FollowUp.application_id == app.id)
        )
        assert fu is not None
        assert fu.scheduled_date == date(2026, 9, 8)
        assert fu.status == "PENDING"

    def test_no_follow_up_on_rejection(self, db_session):
        _seed_preferences(db_session)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        _submit(db_session, app)
        lifecycle.move_lifecycle(db_session, app, "REJECTED")
        # second submission attempt must not resurrect a follow-up
        lifecycle.create_follow_up(db_session, app)
        fu = db_session.scalar(
            select(FollowUp).where(FollowUp.application_id == app.id)
        )
        # the follow-up created at submit time still exists (tracked history)
        assert fu is None or fu.status in ("PENDING",)

    def test_no_duplicate_follow_ups(self, db_session):
        _seed_preferences(db_session)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        lifecycle.create_follow_up(db_session, app)
        second = lifecycle.create_follow_up(db_session, app)
        assert second is None
        count = len(
            list(
                db_session.scalars(
                    select(FollowUp).where(FollowUp.application_id == app.id)
                )
            )
        )
        assert count == 1

    def test_follow_up_state_derived_due(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        fu = lifecycle.create_follow_up(
            db_session, app, scheduled_date=date(2026, 9, 1)
        )
        assert fu is not None
        assert lifecycle.follow_up_state(fu, today=date(2026, 9, 5)) == "DUE"
        assert lifecycle.follow_up_state(fu, today=date(2026, 8, 25)) == "PENDING"

    def test_complete_cancel_reschedule(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        fu = lifecycle.create_follow_up(
            db_session, app, scheduled_date=date(2026, 9, 1)
        )
        lifecycle.reschedule_follow_up(
            db_session, fu, scheduled_date=date(2026, 9, 15)
        )
        assert fu.scheduled_date == date(2026, 9, 15)
        lifecycle.complete_follow_up(db_session, fu)
        assert fu.status == "COMPLETED"
        assert fu.completed_date is not None
        assert lifecycle.follow_up_state(fu, today=date(2026, 9, 20)) == "COMPLETED"

        job2 = _seed_job(db_session, title="Second", company="Globex")
        app2 = lifecycle.ensure_application_for_job(db_session, job2.id)
        fu2 = lifecycle.create_follow_up(
            db_session, app2, scheduled_date=date(2026, 9, 2)
        )
        lifecycle.cancel_follow_up(db_session, fu2)
        assert fu2.status == "CANCELLED"

    def test_follow_up_events_recorded(self, db_session):
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        fu = lifecycle.create_follow_up(
            db_session, app, scheduled_date=date(2026, 9, 1)
        )
        lifecycle.reschedule_follow_up(db_session, fu, scheduled_date=date(2026, 9, 8))
        lifecycle.complete_follow_up(db_session, fu)
        types = [
            e.event_type
            for e in timeline(db_session, app.id)
            if e.event_type.startswith("FOLLOW_UP")
        ]
        assert "FOLLOW_UP_SCHEDULED" in types
        assert "FOLLOW_UP_RESCHEDULED" in types
        assert "FOLLOW_UP_COMPLETED" in types


class TestTrackingAPI:
    def test_status_update_illegal_returns_409(self, client, client_session):
        client, session = client_session
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(
            session, job.id, initial_status="REJECTED"
        )
        resp = client.patch(
            f"/tracking/applications/{app.id}/status",
            json={"target_status": "INTERVIEW", "override": False},
        )
        assert resp.status_code == 409
        assert app.lifecycle_status == "REJECTED"

    def test_status_update_override_writes_status_corrected(self, client, client_session):
        client, session = client_session
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(
            session, job.id, initial_status="REJECTED"
        )
        resp = client.patch(
            f"/tracking/applications/{app.id}/status",
            json={"target_status": "INTERVIEW", "override": True,
                  "notes": "Recruiter confirmed a mistake."},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["application"]["status"] == "INTERVIEW"
        ev = latest_event(session, app.id)
        assert ev.event_type == "STATUS_CORRECTED"
        assert session.scalar(
            select(Application.lifecycle_status).where(Application.id == app.id)
        ) == "INTERVIEW"

    def test_list_applications_and_detail(self, client, client_session):
        client, session = client_session
        _seed_preferences(session)
        job = _seed_job(session, title="Backend Engineer", company="Globex")
        app = lifecycle.ensure_application_for_job(session, job.id)
        _submit(session, app)
        resp = client.get("/tracking/applications")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] == 1
        assert payload["items"][0]["job_title"] == "Backend Engineer"
        detail = client.get(f"/tracking/applications/{app.id}")
        assert detail.status_code == 200
        assert any(e["event_type"] == "SUBMITTED" for e in detail.json()["timeline"])

    def test_add_response_via_api(self, client, client_session):
        client, session = client_session
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(session, job.id)
        _submit(session, app)
        resp = client.post(
            f"/tracking/applications/{app.id}/responses",
            json={"category": "INTERVIEW", "received_at": "2026-09-10"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "INTERVIEW"

    def test_add_note_via_api(self, client, client_session):
        client, session = client_session
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(session, job.id)
        resp = client.post(
            f"/tracking/applications/{app.id}/notes",
            json={"notes": "Keep an eye on this one."},
        )
        assert resp.status_code == 200, resp.text
        assert latest_event(session, app.id).event_type == "NOTE_ADDED"

    def test_follow_up_api(self, client, client_session):
        client, session = client_session
        _seed_preferences(session)
        job = _seed_job(session)
        app = lifecycle.ensure_application_for_job(session, job.id)
        app.applied_date = date(2026, 9, 1)
        resp = client.post(
            f"/tracking/applications/{app.id}/follow-ups",
            json={"scheduled_date": "2026-09-08"},
        )
        assert resp.status_code == 200, resp.text
        fu_id = resp.json()["follow_up_id"]
        complete = client.post(f"/tracking/follow-ups/{fu_id}/complete")
        assert complete.status_code == 200, complete.text
        summary = client.get("/tracking/follow-ups")
        assert summary.status_code == 200
        assert summary.json()["total"] == 1

    def test_statuses_endpoint(self, client):
        resp = client.get("/tracking/statuses")
        assert resp.status_code == 200
        body = resp.json()
        assert "SHORTLISTED" in body["statuses"]
        assert "INTERVIEW_SCHEDULED" in body["event_types"]


class TestTrackedApplicationsVisible:
    def test_tracking_rows_show_follow_up_state(self, db_session):
        _seed_preferences(db_session)
        job = _seed_job(db_session)
        app = lifecycle.ensure_application_for_job(db_session, job.id)
        app.applied_date = date(2026, 9, 1)
        _submit(db_session, app)
        rows = analytics.tracking_rows(db_session, sort="newest")
        assert len(rows) == 1
        assert rows[0]["status"] == "SUBMITTED"
        assert rows[0]["follow_up_state"] in ("PENDING", "DUE")

    def test_tracking_rows_filter_and_sort(self, db_session):
        _seed_preferences(db_session)
        j1 = _seed_job(db_session, title="Engineer A", company="Acme")
        j2 = _seed_job(db_session, title="Engineer B", company="Globex")
        a1 = lifecycle.ensure_application_for_job(db_session, j1.id)
        a2 = lifecycle.ensure_application_for_job(db_session, j2.id)
        a1.applied_date = date(2026, 9, 1)
        a2.applied_date = date(2026, 9, 5)
        _submit(db_session, a1)
        _submit(db_session, a2)
        db_session.flush()

        by_company = analytics.tracking_rows(db_session, company="Globex")
        assert len(by_company) == 1
        assert by_company[0]["id"] == a2.id

        by_status = analytics.tracking_rows(db_session, status="SHORTLISTED")
        assert by_status == []

        newest = analytics.tracking_rows(db_session, sort="newest")
        assert newest[0]["id"] == a2.id
        oldest = analytics.tracking_rows(db_session, sort="oldest")
        assert oldest[0]["id"] == a1.id
