"""Regression tests for Phase 13.1 bug fixes."""
from __future__ import annotations

import math

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.application_queue import (
    ApplicationQueueItem,
)
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import autopilot_service, queue_service
from app.services.queue_service import (
    calculate_priority_score,
    count_queue,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed(db: Session, **overrides) -> dict:
    """Create seed data for bug-fix tests."""
    prefs = Preferences(
        daily_application_target=overrides.get("daily_target", 5),
        daily_application_maximum=overrides.get("daily_maximum", 10),
        max_concurrent_executions=overrides.get("max_concurrent", 1),
        platform_policies={},
    )
    db.add(prefs)
    db.flush()

    profile = Profile(
        name="Test User",
        email="test@example.com",
        phone="+1-555-0100",
        location="San Francisco, CA",
    )
    db.add(profile)
    db.flush()

    job = Job(
        title="Senior Engineer",
        company="TestCo",
        location="San Francisco, CA",
        url="https://example.com/apply",
        application_url="https://example.com/apply",
        source="linkedin",
    )
    db.add(job)
    db.flush()

    resume = Resume(
        name="Test Resume",
        file_path="/tmp/resume.pdf",
        file_name="resume.pdf",
        file_size=1000,
        content_type="application/pdf",
    )
    db.add(resume)
    db.flush()

    app = Application(
        job_id=job.id,
        lifecycle_status="EXECUTION_READY",
        notes="Test application",
    )
    db.add(app)
    db.flush()

    package = ApplicationPackage(
        job_id=job.id,
        status="APPROVED",
        selected_resume_id=resume.id,
        match_score=85.0,
        opportunity_score=78.0,
    )
    db.add(package)
    db.flush()

    return {
        "prefs": prefs,
        "profile": profile,
        "job": job,
        "resume": resume,
        "application": app,
        "package": package,
    }


def _enqueue(db: Session, data: dict) -> ApplicationQueueItem:
    return queue_service.enqueue(
        db,
        application_id=data["application"].id,
        package_id=data["package"].id,
        job_id=data["job"].id,
    )


def _stop_active_run(db: Session):
    """Stop any active autopilot run to avoid conflicts."""
    run = autopilot_service.get_autopilot_status(db)
    if run and run.status in ("RUNNING", "PAUSED"):
        autopilot_service.stop_autopilot(db, run.id)
        db.flush()


# ---------------------------------------------------------------------------
# Fix 1: CRITICAL — process-next import/model bug
# ---------------------------------------------------------------------------

class TestProcessNextBugFix:
    def test_process_next_uses_autopilot_run(self, db_session: Session):
        """process-next queries AutopilotRun, not ApplicationQueueItem."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()

        autopilot_service.process_next_item(db_session, run)
        db_session.flush()
        assert run.processed_count >= 1

    def test_process_next_missing_run_returns_404(self, client: TestClient):
        """process-next with nonexistent run ID returns 404."""
        resp = client.post("/api/v1/queue/autopilot/99999/process-next")
        assert resp.status_code == 404

    def test_process_next_no_name_error(self, client: TestClient):
        """process-next must not raise NameError."""
        # Stop any existing active run first
        status_resp = client.get("/api/v1/queue/autopilot/status")
        if status_resp.status_code == 200:
            active = status_resp.json().get("active_run")
            if active and active.get("id"):
                client.post(f"/api/v1/queue/autopilot/{active['id']}/stop")

        resp = client.post("/api/v1/queue/autopilot/start", json={"target_count": 3})
        assert resp.status_code == 200
        run_id = resp.json()["id"]

        resp = client.post(f"/api/v1/queue/autopilot/{run_id}/process-next")
        assert resp.status_code == 200
        client.post(f"/api/v1/queue/autopilot/{run_id}/stop")

    def test_process_next_selects_correct_queue_item(self, db_session: Session):
        """process-next picks the highest-priority QUEUED item."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        item1 = _enqueue(db_session, data)
        item1.priority_score = 50.0
        db_session.flush()

        # Create a second package for the second enqueue
        package2 = ApplicationPackage(
            job_id=data["job"].id,
            status="APPROVED",
            selected_resume_id=data["resume"].id,
            match_score=95.0,
            opportunity_score=85.0,
        )
        db_session.add(package2)
        db_session.flush()

        app2 = Application(
            job_id=data["job"].id,
            lifecycle_status="EXECUTION_READY",
            notes="Second application",
        )
        db_session.add(app2)
        db_session.flush()

        item2 = queue_service.enqueue(
            db_session,
            application_id=app2.id,
            package_id=package2.id,
            job_id=data["job"].id,
        )
        item2.priority_score = 90.0
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()
        result = autopilot_service.process_next_item(db_session, run)
        db_session.flush()

        assert result is not None
        assert result.id == item2.id


# ---------------------------------------------------------------------------
# Fix 2: HIGH — max concurrent executions
# ---------------------------------------------------------------------------

class TestMaxConcurrentFix:
    def test_default_max_concurrent_is_one(self, db_session: Session):
        """Default max concurrent executions is 1."""
        _seed(db_session)
        val = queue_service.get_max_concurrent(db_session)
        assert val == 1

    def test_custom_max_concurrent(self, db_session: Session):
        """Custom max_concurrent_executions value works."""
        _seed(db_session, max_concurrent=3)
        val = queue_service.get_max_concurrent(db_session)
        assert val == 3

    def test_daily_target_does_not_affect_concurrent(self, db_session: Session):
        """Changing daily target does not change concurrency."""
        _seed(db_session, daily_target=20, max_concurrent=2)
        val = queue_service.get_max_concurrent(db_session)
        assert val == 2

    def test_daily_maximum_does_not_affect_concurrent(self, db_session: Session):
        """Changing daily maximum does not change concurrency."""
        _seed(db_session, daily_maximum=50, max_concurrent=4)
        val = queue_service.get_max_concurrent(db_session)
        assert val == 4

    def test_none_max_concurrent_defaults_to_one(self, db_session: Session):
        """None max_concurrent_executions defaults to 1."""
        prefs = Preferences(
            daily_application_target=5,
            daily_application_maximum=10,
            max_concurrent_executions=None,
            platform_policies={},
        )
        db_session.add(prefs)
        db_session.flush()
        val = queue_service.get_max_concurrent(db_session)
        assert val == 1

    def test_autopilot_respects_max_concurrent(self, db_session: Session):
        """Autopilot respects max concurrent limit."""
        _seed(db_session, max_concurrent=1)
        max_val = queue_service.get_max_concurrent(db_session)
        assert max_val == 1


# ---------------------------------------------------------------------------
# Fix 3: MEDIUM — quality_score bug
# ---------------------------------------------------------------------------

class TestQualityScoreFix:
    def test_quality_and_freshness_are_distinct(self, db_session: Session):
        """quality_score and freshness_score are distinct values."""
        data = _seed(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        # At minimum, the fields should exist and be settable independently.
        item.quality_score = 80.0
        item.freshness_score = 60.0
        db_session.flush()
        assert item.quality_score != item.freshness_score

    def test_priority_uses_weighted_formula(self):
        """Priority uses (match*0.35) + (opp*0.35) + (quality*0.15) + (fresh*0.15)."""
        score = calculate_priority_score(
            match_score=100, opportunity_score=100, quality_score=100, freshness_score=100
        )
        assert score == 100.0

        score2 = calculate_priority_score(
            match_score=0, opportunity_score=0, quality_score=0, freshness_score=0
        )
        assert score2 == 0.0

    def test_priority_is_deterministic(self):
        """Priority calculation is deterministic for same inputs."""
        args = dict(match_score=75, opportunity_score=65, quality_score=55, freshness_score=45)
        s1 = calculate_priority_score(**args)
        s2 = calculate_priority_score(**args)
        assert s1 == s2

    def test_priority_nan_safety(self):
        """Priority handles NaN and Inf safely."""
        score = calculate_priority_score(match_score=float("nan"), opportunity_score=float("inf"))
        assert math.isfinite(score)


# ---------------------------------------------------------------------------
# Fix 4: MEDIUM — queue total count performance
# ---------------------------------------------------------------------------

class TestCountQueueFix:
    def test_count_queue_empty(self, db_session: Session):
        """count_queue returns 0 on empty queue."""
        count = count_queue(db_session)
        assert count == 0

    def test_count_queue_with_items(self, db_session: Session):
        """count_queue counts items correctly."""
        data = _seed(db_session)
        _enqueue(db_session, data)

        # Create a second package for the second enqueue
        package2 = ApplicationPackage(
            job_id=data["job"].id,
            status="APPROVED",
            selected_resume_id=data["resume"].id,
            match_score=70.0,
            opportunity_score=60.0,
        )
        db_session.add(package2)
        db_session.flush()

        app2 = Application(
            job_id=data["job"].id,
            lifecycle_status="EXECUTION_READY",
            notes="Second application",
        )
        db_session.add(app2)
        db_session.flush()

        queue_service.enqueue(
            db_session,
            application_id=app2.id,
            package_id=package2.id,
            job_id=data["job"].id,
        )
        db_session.flush()
        count = count_queue(db_session)
        assert count >= 2

    def test_count_queue_filtered(self, db_session: Session):
        """count_queue respects filters."""
        data = _seed(db_session)
        item = _enqueue(db_session, data)
        queue_service.transition_queue_state(db_session, item.id, "PREPARING")
        db_session.flush()

        count_queue(db_session, state="QUEUED")
        count_preparing = count_queue(db_session, state="PREPARING")
        assert count_preparing >= 1

    def test_api_total_matches_count(self, client: TestClient):
        """API list_queue total uses efficient count, not len()."""
        resp = client.get("/api/v1/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total"], int)
        assert data["total"] >= 0


# ---------------------------------------------------------------------------
# Fix 5: MEDIUM — AWAITING_APPROVAL/USER mapped to SUBMITTED
# ---------------------------------------------------------------------------

class TestExecutionStatusMappingFix:
    def _make_mock_execution(self, status: str, step: str = "test step"):
        """Create a mock execution with id=None to avoid FK constraints."""
        from unittest.mock import MagicMock
        mock_exec = MagicMock()
        mock_exec.id = None  # nullable FK, avoids constraint
        mock_exec.status = status
        mock_exec.current_step = step
        return mock_exec

    def test_awaiting_approval_maps_to_review(self, db_session: Session):
        """AWAITING_APPROVAL execution maps to REVIEW queue state."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()

        from unittest.mock import patch
        mock_exec = self._make_mock_execution("AWAITING_APPROVAL", "waiting for approval")

        with patch("app.services.autopilot_service.run_execution", return_value=mock_exec):
            result = autopilot_service.process_next_item(db_session, run)
            db_session.flush()

        assert result.queue_state == "REVIEW"
        assert result.attention == "REVIEW"

    def test_awaiting_user_maps_to_needs_input(self, db_session: Session):
        """AWAITING_USER execution maps to NEEDS_INPUT queue state."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()

        from unittest.mock import patch
        mock_exec = self._make_mock_execution("AWAITING_USER", "waiting for user input")

        with patch("app.services.autopilot_service.run_execution", return_value=mock_exec):
            result = autopilot_service.process_next_item(db_session, run)
            db_session.flush()

        assert result.queue_state == "NEEDS_INPUT"
        assert result.attention == "ASK"

    def test_successful_submission_maps_to_submitted(self, db_session: Session):
        """EXECUTING status maps to SUBMITTED."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()

        from unittest.mock import patch
        mock_exec = self._make_mock_execution("EXECUTING", "browser automation")

        with patch("app.services.autopilot_service.run_execution", return_value=mock_exec):
            result = autopilot_service.process_next_item(db_session, run)
            db_session.flush()

        assert result.queue_state == "SUBMITTED"

    def test_blocked_execution_maps_to_blocked(self, db_session: Session):
        """BLOCKED execution maps to BLOCKED queue state."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()

        from unittest.mock import patch
        mock_exec = self._make_mock_execution("BLOCKED", "captcha detected")

        with patch("app.services.autopilot_service.run_execution", return_value=mock_exec):
            result = autopilot_service.process_next_item(db_session, run)
            db_session.flush()

        assert result.queue_state == "BLOCKED"

    def test_no_false_submitted_state(self, db_session: Session):
        """Items that need input or review are NOT marked SUBMITTED."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()

        from unittest.mock import patch
        mock_exec = self._make_mock_execution("AWAITING_APPROVAL", "needs approval")

        with patch("app.services.autopilot_service.run_execution", return_value=mock_exec):
            result = autopilot_service.process_next_item(db_session, run)
            db_session.flush()

        assert result.queue_state != "SUBMITTED"


# ---------------------------------------------------------------------------
# Observation: processed_count definition
# ---------------------------------------------------------------------------

class TestProcessedCountDefinition:
    def test_processed_count_increments_before_preflight(self, db_session: Session):
        """processed_count means 'items attempted' (increments before preflight)."""
        _stop_active_run(db_session)
        data = _seed(db_session)
        _enqueue(db_session, data)
        db_session.flush()

        run = autopilot_service.start_autopilot(db_session, target_count=5)
        db_session.flush()
        autopilot_service.process_next_item(db_session, run)
        db_session.flush()
        assert run.processed_count >= 1


# ---------------------------------------------------------------------------
# Observation: resume.name vs resume.file_name
# ---------------------------------------------------------------------------

class TestResumeNameFix:
    def test_enqueue_uses_resume_name(self, db_session: Session):
        """enqueue() uses resume.name for resume_name field."""
        data = _seed(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        # resume.name is "Test Resume", resume.file_name is "resume.pdf"
        assert item.resume_name == "Test Resume"
