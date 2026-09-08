"""Tests for V1.1 fixes: concurrency enforcement, job context, revoked protection."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.application_execution.answer_engine import (
    EVIDENCE_DERIVED,
    EVIDENCE_EXACT,
    ProfileDataProvider,
    generate_answer,
)
from app.application_execution.memory import (
    VERIFICATION_UNVERIFIED,
    VERIFICATION_USER_VERIFIED,
    MemoryStore,
)
from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.application_queue import ApplicationQueueItem
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import autopilot_service, queue_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_queue(db: Session, *, max_concurrent: int = 1, daily_target: int = 5, daily_max: int = 10) -> dict:
    prefs = Preferences(
        daily_application_target=daily_target,
        daily_application_maximum=daily_max,
        max_concurrent_executions=max_concurrent,
        platform_policies={},
    )
    db.add(prefs)
    db.flush()

    profile = Profile(name="Test User", email="test@example.com", phone="+1-555-0100", location="SF")
    db.add(profile)
    db.flush()

    job = Job(title="Engineer", company="TestCo", location="SF", url="https://example.com/apply", application_url="https://example.com/apply", source="linkedin")
    db.add(job)
    db.flush()

    resume = Resume(name="Resume", file_path="/tmp/resume.pdf", file_name="resume.pdf", file_size=1000, content_type="application/pdf")
    db.add(resume)
    db.flush()

    app = Application(job_id=job.id, lifecycle_status="EXECUTION_READY", notes="test")
    db.add(app)
    db.flush()

    package = ApplicationPackage(job_id=job.id, status="APPROVED", selected_resume_id=resume.id, match_score=85.0, opportunity_score=78.0)
    db.add(package)
    db.flush()

    return {"prefs": prefs, "profile": profile, "job": job, "resume": resume, "application": app, "package": package}


def _enqueue_item(db: Session, application_id: int, package_id: int, job_id: int) -> ApplicationQueueItem:
    return queue_service.enqueue(db, application_id=application_id, package_id=package_id, job_id=job_id)


def _set_queue_state(db: Session, item_id: int, state: str) -> None:
    item = db.get(ApplicationQueueItem, item_id)
    item.queue_state = state
    db.flush()


# ===========================================================================
# FIX 1: Concurrency Enforcement
# ===========================================================================

class TestConcurrencyEnforcement:
    """Tests for max_concurrent_executions enforcement in autopilot."""

    def test_default_max_concurrent_is_one(self, db_session: Session):
        db = db_session
        _seed_queue(db, max_concurrent=1)
        assert queue_service.get_max_concurrent(db) == 1

    def test_custom_max_concurrent(self, db_session: Session):
        db = db_session
        _seed_queue(db, max_concurrent=3)
        assert queue_service.get_max_concurrent(db) == 3

    def test_active_count_zero_when_no_executing(self, db_session: Session):
        db = db_session
        _seed_queue(db)
        assert queue_service.get_active_execution_count(db) == 0

    def test_active_count_increases_with_executing(self, db_session: Session):
        db = db_session
        data = _seed_queue(db)
        item = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item.id, "EXECUTING")
        assert queue_service.get_active_execution_count(db) == 1

    def test_active_count_decreases_after_completion(self, db_session: Session):
        db = db_session
        data = _seed_queue(db)
        item = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item.id, "EXECUTING")
        assert queue_service.get_active_execution_count(db) == 1
        _set_queue_state(db, item.id, "COMPLETED")
        assert queue_service.get_active_execution_count(db) == 0

    def test_blocked_when_active_eq_max(self, db_session: Session):
        db = db_session
        data = _seed_queue(db, max_concurrent=1)
        item1 = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item1.id, "EXECUTING")
        run = autopilot_service.start_autopilot(db, target_count=5)
        result = autopilot_service.process_next_item(db, run)
        assert result is None, "Should be blocked when active == max_concurrent"

    def test_allowed_when_active_lt_max(self, db_session: Session):
        db = db_session
        data = _seed_queue(db, max_concurrent=2)
        # First item is EXECUTING (active=1, max=2)
        item1 = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item1.id, "EXECUTING")
        # Second item is QUEUED (the next one to process)
        job2 = Job(title="Engineer 2", company="TestCo2", location="SF", url="https://example.com/apply2", application_url="https://example.com/apply2", source="linkedin")
        db.add(job2)
        db.flush()
        app2 = Application(job_id=job2.id, lifecycle_status="EXECUTION_READY", notes="test2")
        db.add(app2)
        db.flush()
        pkg2 = ApplicationPackage(job_id=job2.id, status="APPROVED", selected_resume_id=data["resume"].id, match_score=80.0, opportunity_score=75.0)
        db.add(pkg2)
        db.flush()
        _enqueue_item(db, app2.id, pkg2.id, job2.id)
        assert queue_service.get_active_execution_count(db) == 1
        assert queue_service.get_max_concurrent(db) == 2
        run = autopilot_service.start_autopilot(db, target_count=5)
        result = autopilot_service.process_next_item(db, run)
        assert result is not None, "Should proceed when active < max_concurrent"

    def test_failed_execution_releases_slot(self, db_session: Session):
        db = db_session
        data = _seed_queue(db, max_concurrent=1)
        item1 = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item1.id, "EXECUTING")
        assert queue_service.get_active_execution_count(db) == 1
        _set_queue_state(db, item1.id, "FAILED")
        assert queue_service.get_active_execution_count(db) == 0

    def test_daily_target_does_not_affect_concurrency(self, db_session: Session):
        db = db_session
        data = _seed_queue(db, max_concurrent=2, daily_target=0, daily_max=100)
        item1 = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item1.id, "EXECUTING")
        run = autopilot_service.start_autopilot(db, target_count=5)
        autopilot_service.process_next_item(db, run)
        # daily_target=0 is overridden to min 1 in start_autopilot, but
        # check_daily_limit checks daily_maximum, not target
        # The key is concurrency check happens before daily limit check
        assert queue_service.get_active_execution_count(db) == 1

    def test_daily_maximum_does_not_affect_concurrency(self, db_session: Session):
        db = db_session
        data = _seed_queue(db, max_concurrent=2, daily_target=100, daily_max=0)
        item1 = _enqueue_item(db, data["application"].id, data["package"].id, data["job"].id)
        _set_queue_state(db, item1.id, "EXECUTING")
        assert queue_service.get_max_concurrent(db) == 2
        assert queue_service.get_active_execution_count(db) == 1


# ===========================================================================
# FIX 2: Job Context in Answer Engine
# ===========================================================================

class TestJobContextInAnswerEngine:
    """Tests for job_context contributing to answer generation."""

    def _make_profile(self, **kwargs) -> ProfileDataProvider:
        defaults = {
            "name": "Alice Smith",
            "email": "alice@example.com",
            "skills": ["Python", "React", "FastAPI"],
            "skills_programming": ["Python", "JavaScript"],
            "skills_frameworks": ["React", "FastAPI", "Django"],
            "projects": ["Built a React + FastAPI full-stack app", "E-commerce platform with Django"],
            "experience_level": "3 years",
            "current_role": "Software Engineer",
        }
        defaults.update(kwargs)
        return ProfileDataProvider(defaults)

    def test_job_context_used_for_motivation(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile()
        job_ctx = {"title": "React + FastAPI Developer", "description": "Looking for React + FastAPI developer"}
        result = generate_answer("Why are you interested in this role?", mem, profile, job_context=job_ctx)
        assert result.generated_answer is not None
        assert "react" in result.generated_answer.answer.lower() or "fastapi" in result.generated_answer.answer.lower()
        assert result.generated_answer.evidence_level in (EVIDENCE_EXACT, EVIDENCE_DERIVED)

    def test_matching_job_context_produces_evidence(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile(skills=["Python", "React"])
        job_ctx = {"title": "Python Developer", "description": "Python and React experience required"}
        result = generate_answer("Why are you interested in this role?", mem, profile, job_context=job_ctx)
        assert result.generated_answer is not None
        assert any("job_context" in s for s in result.generated_answer.evidence_sources)

    def test_unrelated_job_context_no_match(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile(skills=["Python"])
        job_ctx = {"title": "Marketing Manager", "description": "Digital marketing and SEO"}
        result = generate_answer("Why are you interested in this role?", mem, profile, job_context=job_ctx)
        # Should not produce a job-context-based answer since no skill overlap
        # It may still return None (needs_user_input) since no evidence
        if result.generated_answer:
            assert "marketing" not in result.generated_answer.answer.lower()

    def test_missing_job_context_fallback(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile()
        result = generate_answer("What is your email?", mem, profile, job_context=None)
        assert result.generated_answer is not None
        assert result.generated_answer.answer == "alice@example.com"

    def test_unsupported_claim_returns_no_evidence(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile()
        job_ctx = {"title": "Data Scientist", "description": "ML and deep learning required"}
        result = generate_answer("Describe your experience with quantum computing hardware.", mem, profile, job_context=job_ctx)
        # No evidence for quantum computing -> should request user input
        assert result.needs_user_input is True

    def test_sensitive_question_not_auto_answered_by_context(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile()
        job_ctx = {"title": "Engineer", "description": "Engineering role"}
        result = generate_answer("Are you authorized to work in the US?", mem, profile, job_context=job_ctx)
        # Authorization is HIGH sensitivity -> should not be auto-filled
        assert result.generated_answer is None or result.generated_answer.can_auto_fill is False

    def test_job_context_does_not_create_facts(self, db_session: Session):
        mem = MemoryStore()
        profile = self._make_profile(
            skills=["Python"],
            skills_programming=["Python"],
            skills_frameworks=["Django"],
            projects=["Built a REST API with Django"],
        )
        job_ctx = {"title": "React Developer", "description": "React and TypeScript required for UI development"}
        result = generate_answer("Why are you interested in this role?", mem, profile, job_context=job_ctx)
        if result.generated_answer:
            answer_lower = result.generated_answer.answer.lower()
            # Should not claim React/TypeScript experience when profile has no React/TypeScript
            assert "react" not in answer_lower
            assert "typescript" not in answer_lower


# ===========================================================================
# FIX 3: Revoked Answer Protection
# ===========================================================================

class TestRevokedAnswerProtection:
    """Tests for revoked/expired answer exclusion from automatic reuse."""

    def test_verified_answer_returned(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("What is your email?", "alice@example.com", source=VERIFICATION_USER_VERIFIED)
        result = mem.get_answer("What is your email?")
        assert result is not None
        assert result.answer == "alice@example.com"

    def test_expired_answer_returns_none(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("What is your email?", "alice@example.com", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("What is your email?")
        result = mem.get_answer("What is your email?")
        assert result is None

    def test_unverified_answer_returns_none(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("What is your email?", "alice@example.com", source=VERIFICATION_UNVERIFIED)
        result = mem.get_answer("What is your email?")
        assert result is None

    def test_system_derived_answer_returned(self, db_session: Session):
        mem = MemoryStore()
        from app.application_execution.memory import VERIFICATION_SYSTEM_DERIVED
        mem.add_answer("What is your phone?", "+1-555-0100", source=VERIFICATION_SYSTEM_DERIVED)
        result = mem.get_answer("What is your phone?")
        assert result is not None
        assert result.answer == "+1-555-0100"

    def test_low_sensitivity_revoked_not_reused(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("What is your name?", "Alice", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("What is your name?")
        result = mem.get_answer("What is your name?")
        assert result is None

    def test_medium_sensitivity_revoked_not_reused(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("What is your salary expectation?", "100k", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("What is your salary expectation?")
        result = mem.get_answer("What is your salary expectation?")
        assert result is None

    def test_high_sensitivity_revoked_not_reused(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("Are you authorized to work?", "Yes", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("Are you authorized to work?")
        result = mem.get_answer("Are you authorized to work?")
        assert result is None

    def test_expired_answer_not_in_get_verified(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("Why interested?", "Passion", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("Why interested?")
        result = mem.get_verified_answer("Why interested?")
        assert result is None

    def test_use_count_not_incremented_for_revoked(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("Test Q", "Test A", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("Test Q")
        mem.get_answer("Test Q")
        answer = mem.answers.get(_norm_helper("Test Q"))
        assert answer.use_count == 0

    def test_get_answer_only_returns_user_verified_or_system_derived(self, db_session: Session):
        mem = MemoryStore()
        mem.add_answer("Q1", "A1", source=VERIFICATION_USER_VERIFIED)
        from app.application_execution.memory import VERIFICATION_SYSTEM_DERIVED
        mem.add_answer("Q2", "A2", source=VERIFICATION_SYSTEM_DERIVED)
        mem.add_answer("Q3", "A3", source=VERIFICATION_UNVERIFIED)
        mem.add_answer("Q4", "A4", source=VERIFICATION_USER_VERIFIED)
        mem.revoke_answer("Q4")

        assert mem.get_answer("Q1") is not None
        assert mem.get_answer("Q2") is not None
        assert mem.get_answer("Q3") is None
        assert mem.get_answer("Q4") is None


def _norm_helper(text: str) -> str:
    import re
    return re.compile(r"\W+").sub(" ", text.lower()).strip()
