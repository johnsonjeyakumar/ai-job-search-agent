"""Phase 9.1 QA regression tests.

Covers the four defect fixes from the full-system QA pass:
- DEF1 (P1): execution-confirmed submission lands at SUBMISSION_CONFIRMED
- DEF2 (P2): complete/cancel on finished follow-up returns 409
- DEF3 (P2): invalid target status returns 422
- DEF4 (P3): dashboard avg_match / avg_opportunity field names
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.application_execution import base
from app.models.application import Application, FollowUp
from app.models.application_tracking import ApplicationEvent
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import job_service

# ---------------------------------------------------------------------------
# Helpers (reuse the established pattern from test_phase7).
# ---------------------------------------------------------------------------

def _seed_profile(db):
    profile = Profile(
        name="QA 9.1 Candidate",
        email="qa91@example.test",
        city="Chennai",
        skills=["Python", "SQL"],
        skills_programming=["Python"],
        skills_databases=["SQL"],
        experience_level="0-2 years",
    )
    db.add(profile)
    db.flush()
    return profile


def _seed_preferences(db):
    prefs = Preferences(
        preferred_locations=["Chennai"],
        experience_levels=["0-2 years"],
        target_roles=["Software Developer"],
        remote_types=["remote", "hybrid", "onsite"],
        employment_types=["full_time"],
        salary_min=4,
        salary_max=8,
    )
    db.add(prefs)
    db.flush()
    return prefs


def _seed_resume(db, profile):
    resume = Resume(
        profile_id=profile.id,
        name="qa91_resume.pdf",
        target_role="Software Developer",
        file_path="resumes/qa91.pdf",
        file_name="qa91_resume.pdf",
        file_size=100,
        content_type="application/pdf",
        version="v1",
    )
    db.add(resume)
    db.flush()
    return resume


def _insert_job(db, *, url="mock://simple-form", app_url=None):
    record = {
        "title": "QA 9.1 Developer",
        "company": "QA Corp",
        "source": "apify",
        "source_job_id": "qa91-job",
        "url": url,
        "application_url": app_url,
        "location": "Chennai",
        "remote_type": "onsite",
        "employment_type": "full_time",
        "description": "QA 9.1 regression job.",
        "requirements": [],
        "skills": ["Python"],
    }
    result = job_service.insert_jobs(db, [record], source="apify")
    assert result.inserted == 1
    return db.scalar(select(Job).order_by(Job.id.desc()))


def _approved_package(client, session, *, url="mock://simple-form", app_url=None):
    profile = _seed_profile(session)
    _seed_preferences(session)
    _seed_resume(session, profile)
    job = _insert_job(session, url=url, app_url=app_url)
    session.commit()

    # prepare + approve
    resp = client.post(
        "/applications/prepare",
        json={"job_id": job.id, "include_cover_letter": False},
    )
    assert resp.status_code == 200
    package_id = resp.json()["package"]["id"]

    resp = client.post(f"/applications/{package_id}/approve")
    assert resp.status_code == 200
    return package_id


# ---------------------------------------------------------------------------
# DEF1 tests: execution-confirmed submission
# ---------------------------------------------------------------------------

class TestDEF1_FirstExecutionConfirmation:
    """First confirmed execution must create a tracker row at
    SUBMISSION_CONFIRMED (not DISCOVERED), record the correct events,
    and schedule a follow-up."""

    def test_new_row_lands_at_submission_confirmed(self, client_session):
        client, session = client_session
        package_id = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        # execute + approve (auto-confirms for company_career)
        exec_resp = client.post(
            f"/applications/{package_id}/execute",
            json={"driver": "mock"},
        )
        execution = exec_resp.json()["execution"]
        assert execution["status"] == base.STATUS_AWAITING_APPROVAL

        approve_resp = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve",
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["execution"]["status"] == base.STATUS_SUBMISSION_CONFIRMED

        # tracker row must exist at SUBMISSION_CONFIRMED
        app_row = session.scalar(select(Application).order_by(Application.id.desc()))
        assert app_row is not None
        assert app_row.lifecycle_status == "SUBMISSION_CONFIRMED"
        assert app_row.status == "submitted"

    def test_first_confirm_records_correct_events(self, client_session):
        client, session = client_session
        package_id = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        exec_resp = client.post(
            f"/applications/{package_id}/execute",
            json={"driver": "mock"},
        )
        execution = exec_resp.json()["execution"]
        client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve",
        )

        app_row = session.scalar(select(Application).order_by(Application.id.desc()))
        events = list(
            session.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == app_row.id)
                .order_by(ApplicationEvent.id)
            )
        )
        event_types = [e.event_type for e in events]

        # Must have APPLICATION_CREATED + SUBMISSION_CONFIRMED (no misleading
        # "Repeat submission" event).
        assert "APPLICATION_CREATED" in event_types
        assert "SUBMISSION_CONFIRMED" in event_types
        # The repeat-submission event must NOT appear on first confirmation.
        repeat_events = [
            e for e in events
            if e.notes and "Repeat submission" in (e.notes or "")
        ]
        assert len(repeat_events) == 0

        # APPLICATION_CREATED must record the correct target status, not DISCOVERED.
        created_event = next(e for e in events if e.event_type == "APPLICATION_CREATED")
        assert created_event.new_status == "SUBMISSION_CONFIRMED"

    def test_first_confirm_schedules_follow_up(self, client_session):
        client, session = client_session
        package_id = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        exec_resp = client.post(
            f"/applications/{package_id}/execute",
            json={"driver": "mock"},
        )
        execution = exec_resp.json()["execution"]
        client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve",
        )

        app_row = session.scalar(select(Application).order_by(Application.id.desc()))
        follow_ups = list(
            session.scalars(
                select(FollowUp).where(FollowUp.application_id == app_row.id)
            )
        )
        assert len(follow_ups) == 1
        assert follow_ups[0].reason == "SUBMISSION_FOLLOW_UP"
        assert follow_ups[0].priority == "MEDIUM"
        assert follow_ups[0].status == "PENDING"


class TestDEF1_RepeatedExecutionConfirmation:
    """Repeated confirmation of the same execution must NOT create duplicate
    submission events or duplicate follow-ups."""

    def test_repeat_confirm_no_duplicate_follow_up(self, client_session):
        client, session = client_session
        package_id = _approved_package(
            client, session,
            url="mock://careers.acme.com/apply/simple-form",
            app_url="mock://careers.acme.com/apply/simple-form",
        )
        exec_resp = client.post(
            f"/applications/{package_id}/execute",
            json={"driver": "mock"},
        )
        execution = exec_resp.json()["execution"]

        # First confirmation
        client.post(
            f"/applications/{package_id}/execution/{execution['id']}/approve",
        )

        app_row = session.scalar(select(Application).order_by(Application.id.desc()))
        fu_count_before = len(list(
            session.scalars(
                select(FollowUp).where(FollowUp.application_id == app_row.id)
            )
        ))

        # Attempt a second confirm via the confirm endpoint (the execution
        # is already SUBMISSION_CONFIRMED so the guard should reject it)
        resp = client.post(
            f"/applications/{package_id}/execution/{execution['id']}/confirm",
            json={"verification": "CONFIRMED", "reference": "REPEAT-1"},
        )
        assert resp.status_code == 409  # already confirmed

        fu_count_after = len(list(
            session.scalars(
                select(FollowUp).where(FollowUp.application_id == app_row.id)
            )
        ))
        assert fu_count_after == fu_count_before


# ---------------------------------------------------------------------------
# DEF2 tests: finished follow-up actions
# ---------------------------------------------------------------------------

class TestDEF2_FinishedFollowUpActions:
    """complete/cancel on a finished follow-up must return 409."""

    def _make_follow_up(self, session, app_id, *, status="PENDING"):
        fu = FollowUp(
            application_id=app_id,
            action_type="follow_up",
            reason="SUBMISSION_FOLLOW_UP",
            priority="MEDIUM",
            trigger_status="SUBMITTED",
            trigger_key=f"test:{app_id}:fu",
            scheduled_date=date(2026, 10, 1),
            status=status,
        )
        session.add(fu)
        session.flush()
        return fu

    def test_complete_on_completed_returns_409(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()

        fu = self._make_follow_up(session, app.id, status="COMPLETED")
        session.commit()

        resp = client.post(
            f"/tracking/follow-ups/{fu.id}/complete",
            json={},
        )
        assert resp.status_code == 409
        assert "already finished" in resp.json()["detail"].lower()

    def test_cancel_on_cancelled_returns_409(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()

        fu = self._make_follow_up(session, app.id, status="CANCELLED")
        session.commit()

        resp = client.post(
            f"/tracking/follow-ups/{fu.id}/cancel",
            json={},
        )
        assert resp.status_code == 409
        assert "already finished" in resp.json()["detail"].lower()

    def test_complete_on_pending_succeeds(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()

        fu = self._make_follow_up(session, app.id, status="PENDING")
        session.commit()

        resp = client.post(
            f"/tracking/follow-ups/{fu.id}/complete",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Follow-up completed."

    def test_cancel_on_pending_succeeds(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()

        fu = self._make_follow_up(session, app.id, status="PENDING")
        session.commit()

        resp = client.post(
            f"/tracking/follow-ups/{fu.id}/cancel",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Follow-up cancelled."


# ---------------------------------------------------------------------------
# DEF3 tests: invalid target status
# ---------------------------------------------------------------------------

class TestDEF3_InvalidTargetStatus:
    """Invalid status strings must return 422, not 500."""

    def test_invalid_status_string_returns_422(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()
        session.commit()

        resp = client.patch(
            f"/tracking/applications/{app.id}/status",
            json={"target_status": "BOGUS_STATUS"},
        )
        assert resp.status_code == 422
        assert "Invalid application status" in resp.json()["detail"]

    def test_valid_illegal_transition_returns_409(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()
        session.commit()

        # SUBMISSION_CONFIRMED -> EXECUTING is illegal
        resp = client.patch(
            f"/tracking/applications/{app.id}/status",
            json={"target_status": "EXECUTING"},
        )
        assert resp.status_code == 409
        assert "Illegal transition" in resp.json()["detail"]

    def test_valid_legal_transition_succeeds(self, client_session):
        client, session = client_session
        profile = _seed_profile(session)
        job = _insert_job(session)
        app = Application(
            job_id=job.id,
            profile_id=profile.id,
            status="submitted",
            lifecycle_status="SUBMISSION_CONFIRMED",
            applied_date=date.today(),
        )
        session.add(app)
        session.flush()
        session.commit()

        # SUBMISSION_CONFIRMED -> RESPONSE_RECEIVED is legal
        resp = client.patch(
            f"/tracking/applications/{app.id}/status",
            json={"target_status": "RESPONSE_RECEIVED"},
        )
        assert resp.status_code == 200
        assert "RESPONSE_RECEIVED" in resp.json()["message"]


# ---------------------------------------------------------------------------
# DEF4 tests: dashboard field names
# ---------------------------------------------------------------------------

class TestDEF4_DashboardFieldNames:
    """Dashboard must receive average_match_score / average_opportunity_score
    from the backend and render them correctly."""

    def test_jobs_stats_returns_correct_field_names(self, client_session):
        client, session = client_session
        resp = client.get("/jobs/stats")
        assert resp.status_code == 200
        stats = resp.json()
        matches = stats.get("matches", {})
        # Backend uses average_match_score / average_opportunity_score
        assert "average_match_score" in matches
        assert "average_opportunity_score" in matches
        # Frontend-stale names must not exist at this level
        assert "avg_match_score" not in matches
        assert "avg_opportunity_score" not in matches
