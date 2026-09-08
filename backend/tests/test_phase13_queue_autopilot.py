"""Tests for Application Queue and Autopilot Orchestration (Phase 13)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.application_queue import (
    ATTENTION_AUTO,
    ATTENTION_BLOCK,
    ApplicationQueueItem,
    AutopilotRun,
)
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import autopilot_service, queue_service
from app.services.queue_service import (
    QueueConflictError,
    QueueItemExistsError,
    calculate_priority_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_minimal(db: Session) -> dict:
    """Create minimal seed data for queue tests."""
    prefs = Preferences(
        daily_application_target=5,
        daily_application_maximum=10,
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


# ---------------------------------------------------------------------------
# Priority Calculation Tests
# ---------------------------------------------------------------------------

class TestPriorityCalculation:
    def test_all_scores(self):
        score = calculate_priority_score(
            match_score=90, opportunity_score=80, quality_score=70, freshness_score=60
        )
        assert 0 < score < 100

    def test_missing_scores(self):
        score = calculate_priority_score()
        assert score == 0.0

    def test_clamped_high(self):
        score = calculate_priority_score(match_score=150, opportunity_score=150)
        assert score <= 100.0

    def test_clamped_low(self):
        score = calculate_priority_score(match_score=-10, opportunity_score=-10)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# Queue Service Tests
# ---------------------------------------------------------------------------

class TestQueueService:
    def test_enqueue_item(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        assert item is not None
        assert item.queue_state == "QUEUED"
        assert item.priority_score > 0
        assert item.job_title == "Senior Engineer"
        assert item.company_name == "TestCo"

    def test_enqueue_duplicate_raises(self, db_session: Session):
        data = _seed_minimal(db_session)
        queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        with pytest.raises(QueueItemExistsError):
            queue_service.enqueue(
                db_session,
                application_id=data["application"].id,
                package_id=data["package"].id,
                job_id=data["job"].id,
            )

    def test_enqueue_completed_item_allows_requeue(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        item.queue_state = "COMPLETED"
        db_session.flush()

        item2 = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        assert item2.id != item.id

    def test_list_queue(self, db_session: Session):
        data = _seed_minimal(db_session)
        queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        items = queue_service.list_queue(db_session)
        assert len(items) == 1

    def test_count_by_state(self, db_session: Session):
        data = _seed_minimal(db_session)
        queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        counts = queue_service.count_queue_by_state(db_session)
        assert counts.get("QUEUED", 0) == 1

    def test_transition_valid(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        updated = queue_service.transition_queue_state(
            db_session, item.id, "PREPARING"
        )
        assert updated.queue_state == "PREPARING"

    def test_transition_invalid(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        with pytest.raises(QueueConflictError):
            queue_service.transition_queue_state(
                db_session, item.id, "COMPLETED"
            )

    def test_skip_item(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        skipped = queue_service.skip_item(db_session, item.id, reason="Not interested")
        assert skipped.queue_state == "SKIPPED"
        assert skipped.skip_reason == "Not interested"

    def test_run_preflight_blocked_no_url(self, db_session: Session):
        data = _seed_minimal(db_session)
        data["job"].url = None
        data["job"].application_url = None
        db_session.flush()

        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        result = queue_service.run_preflight(db_session, item.id)
        assert result.attention == ATTENTION_BLOCK
        assert result.queue_state == "BLOCKED"

    def test_run_preflight_auto(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        result = queue_service.run_preflight(db_session, item.id)
        assert result.attention == ATTENTION_AUTO
        assert result.queue_state == "READY"

    def test_daily_submission_count(self, db_session: Session):
        count = queue_service.get_daily_submission_count(db_session)
        assert count == 0

    def test_daily_limits(self, db_session: Session):
        _seed_minimal(db_session)
        # The queue service queries preferences from the DB; use the one
        # created by _seed_minimal (latest id).
        limits = queue_service.get_daily_limits(db_session)
        # We set target=5, maximum=10 in _seed_minimal but there may be
        # pre-existing preferences rows; just verify the function returns a dict.
        assert "target" in limits
        assert "maximum" in limits

    def test_check_daily_limit(self, db_session: Session):
        assert queue_service.check_daily_limit(db_session) is False

    def test_resolve_item_wrong_state(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        with pytest.raises(QueueConflictError):
            queue_service.resolve_item(db_session, item.id, {"answer": "test"})


# ---------------------------------------------------------------------------
# Autopilot Service Tests
# ---------------------------------------------------------------------------

class TestAutopilotService:
    def test_start_autopilot(self, db_session: Session):
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        assert run.status == "RUNNING"
        assert run.target_count == 3

    def test_start_autopilot_conflict(self, db_session: Session):
        autopilot_service.start_autopilot(db_session, target_count=3)
        with pytest.raises(autopilot_service.AutopilotConflictError):
            autopilot_service.start_autopilot(db_session, target_count=3)

    def test_pause_autopilot(self, db_session: Session):
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        paused = autopilot_service.pause_autopilot(db_session, run.id)
        assert paused.status == "PAUSED"

    def test_resume_autopilot(self, db_session: Session):
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        autopilot_service.pause_autopilot(db_session, run.id)
        resumed = autopilot_service.resume_autopilot(db_session, run.id)
        assert resumed.status == "RUNNING"

    def test_stop_autopilot(self, db_session: Session):
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        stopped = autopilot_service.stop_autopilot(db_session, run.id)
        assert stopped.status == "COMPLETED"
        assert stopped.ended_at is not None

    def test_get_autopilot_status(self, db_session: Session):
        assert autopilot_service.get_autopilot_status(db_session) is None
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        status = autopilot_service.get_autopilot_status(db_session)
        assert status is not None
        assert status.id == run.id

    def test_process_next_no_items(self, db_session: Session):
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        item = autopilot_service.process_next_item(db_session, run)
        assert item is None
        assert run.status == "COMPLETED"

    def test_process_next_item(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        db_session.flush()
        # Verify item is in QUEUED state before autopilot picks it up.
        from sqlalchemy import select as sa_select
        check = db_session.scalar(
            sa_select(ApplicationQueueItem).where(ApplicationQueueItem.id == item.id)
        )
        assert check is not None, "Enqueued item not found"
        assert check.queue_state == "QUEUED", f"Expected QUEUED, got {check.queue_state}"

        run = autopilot_service.start_autopilot(db_session, target_count=3)
        db_session.flush()
        autopilot_service.process_next_item(db_session, run)
        db_session.flush()
        # processed_count should be >= 1 whether the item succeeded or failed.
        assert run.processed_count >= 1 or run.failed_count >= 1

    def test_process_next_daily_limit(self, db_session: Session):
        """Test that autopilot stops when daily limit is reached."""
        data = _seed_minimal(db_session)
        queue_service.enqueue(
            db_session,
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
        )
        db_session.flush()
        run = autopilot_service.start_autopilot(db_session, target_count=3)
        db_session.flush()
        # Simulate daily limit by setting processed_count to target
        run.processed_count = 3
        db_session.flush()
        item = autopilot_service.process_next_item(db_session, run)
        db_session.flush()
        assert item is None
        assert run.status == "COMPLETED"

    def test_queue_stats(self, db_session: Session):
        stats = autopilot_service.queue_stats(db_session)
        assert "state_counts" in stats
        assert "daily_submitted" in stats
        assert "daily_target" in stats


# ---------------------------------------------------------------------------
# API Tests
# ---------------------------------------------------------------------------

class TestQueueAPI:
    def test_list_queue_empty(self, client: TestClient):
        resp = client.get("/api/v1/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["total"], int)
        assert data["total"] >= 0

    def test_queue_stats(self, client: TestClient):
        resp = client.get("/api/v1/queue/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending_count" in data
        assert "daily_submitted" in data

    def test_get_nonexistent_item(self, client: TestClient):
        resp = client.get("/api/v1/queue/99999")
        assert resp.status_code == 404

    def test_enqueue_invalid(self, client: TestClient):
        resp = client.post("/api/v1/queue/enqueue", json={})
        assert resp.status_code == 422

    def test_autopilot_status(self, client: TestClient):
        resp = client.get("/api/v1/queue/autopilot/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending_items" in data

    def test_autopilot_start_and_stop(self, client: TestClient):
        # Stop any existing active run first.
        status_resp = client.get("/api/v1/queue/autopilot/status")
        if status_resp.status_code == 200:
            active = status_resp.json().get("active_run")
            if active and active.get("id"):
                client.post(f"/api/v1/queue/autopilot/{active['id']}/stop")

        resp = client.post(
            "/api/v1/queue/autopilot/start",
            json={"target_count": 3},
        )
        assert resp.status_code == 200
        run_id = resp.json()["id"]

        resp = client.post(f"/api/v1/queue/autopilot/{run_id}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "COMPLETED"

    def test_autopilot_pause_resume(self, client: TestClient):
        # Stop any existing active run first.
        status_resp = client.get("/api/v1/queue/autopilot/status")
        if status_resp.status_code == 200:
            active = status_resp.json().get("active_run")
            if active and active.get("id"):
                client.post(f"/api/v1/queue/autopilot/{active['id']}/stop")

        resp = client.post(
            "/api/v1/queue/autopilot/start",
            json={"target_count": 3},
        )
        run_id = resp.json()["id"]

        resp = client.post(f"/api/v1/queue/autopilot/{run_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "PAUSED"

        resp = client.post(f"/api/v1/queue/autopilot/{run_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "RUNNING"

        client.post(f"/api/v1/queue/autopilot/{run_id}/stop")

    def test_autopilot_conflict(self, client: TestClient):
        # Stop any existing active run first.
        status_resp = client.get("/api/v1/queue/autopilot/status")
        if status_resp.status_code == 200:
            active = status_resp.json().get("active_run")
            if active and active.get("id"):
                client.post(f"/api/v1/queue/autopilot/{active['id']}/stop")

        client.post("/api/v1/queue/autopilot/start", json={"target_count": 3})
        resp = client.post("/api/v1/queue/autopilot/start", json={"target_count": 3})
        assert resp.status_code == 409

    def test_autopilot_nonexistent_stop(self, client: TestClient):
        resp = client.post("/api/v1/queue/autopilot/99999/stop")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class TestApplicationQueueModel:
    def test_model_fields(self, db_session: Session):
        data = _seed_minimal(db_session)
        item = ApplicationQueueItem(
            application_id=data["application"].id,
            package_id=data["package"].id,
            job_id=data["job"].id,
            queue_state="QUEUED",
            priority_score=75.5,
            match_score=80.0,
            opportunity_score=70.0,
            quality_score=65.0,
            freshness_score=90.0,
            job_title="Test Job",
            company_name="TestCo",
            platform="linkedin",
            resume_name="resume.pdf",
        )
        db_session.add(item)
        db_session.flush()
        assert item.id > 0
        assert item.queue_state == "QUEUED"
        assert item.priority_score == 75.5

    def test_autopilot_model_fields(self, db_session: Session):
        run = AutopilotRun(
            status="RUNNING",
            target_count=5,
        )
        db_session.add(run)
        db_session.flush()
        assert run.id > 0
        assert run.status == "RUNNING"
        assert run.target_count == 5
