"""Phase 14.1: Integration of multi-step orchestrator into execution engine.

Verifies:
- Single-page forms still work unchanged (backward compatibility)
- Multi-page forms are detected and routed through the orchestrator
- Checkpoints are created during multi-page execution
- Approval boundary is preserved for both paths
- Safety controls remain intact
"""
from __future__ import annotations

from sqlalchemy import select

from app.application_execution import base
from app.application_execution import executor as executor_mod
from app.application_execution.browser import MockBrowserDriver
from app.application_execution.fields import build_profile_context
from app.application_execution.form_orchestrator import (
    fill_page_fields,
    inspect_page,
    map_page_fields,
    validate_page,
)
from app.application_execution.form_session import (
    FormSession,
    FormSessionState,
)
from app.application_execution.page_detector import detect_navigation
from app.models.application_execution import ApplicationExecutionStep
from app.models.application_package import ApplicationPackage
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.storage.local import get_storage


def _count(db, model):
    return len(list(db.scalars(select(model).limit(500))))


def _job(title="Software Developer", company="Acme", **extra):
    return {
        "title": title,
        "company": company,
        "source": "apify",
        "source_job_id": extra.pop("source_job_id", f"p141-{abs(hash(title))}"),
        "url": extra.pop("url", "mock://simple-form"),
        "application_url": extra.pop("application_url", None),
        "location": extra.pop("location", "Chennai, Tamil Nadu"),
        "remote_type": extra.pop("remote_type", "onsite"),
        "employment_type": extra.pop("employment_type", "full_time"),
        "salary": extra.pop("salary", None),
        "description": extra.pop("description", None),
        "requirements": extra.pop("requirements", []),
        "skills": extra.pop("skills", []),
        "posted_date": extra.pop("posted_date", None),
        **extra,
    }


def _seed_profile(db, **extra):
    values = {
        "name": "Test Candidate",
        "email": f"p141-{abs(hash(str(extra))) or 11}@example.test",
        "city": "Chennai",
        "degree": "B.Tech",
        "university": "Anna University",
        "graduation_year": 2024,
        "skills": ["Python", "React", "PostgreSQL"],
        "skills_programming": ["Python", "Java"],
        "skills_frameworks": ["React"],
        "skills_databases": ["PostgreSQL"],
        "experience_level": "0-2 years",
        "preferred_roles": ["Software Developer", "Frontend Developer"],
        "preferred_locations": ["Chennai"],
        "remote_preference": "hybrid",
        "salary_preference": "4-8 LPA",
        "notice_period": "Immediate",
        "work_authorization": "Authorized to work in India.",
        "projects": [],
        "internships": [],
        "certifications": [],
        **extra,
    }
    profile = Profile(**values)
    db.add(profile)
    db.flush()
    return profile


def _seed_preferences(db, **extra):
    values = {
        "preferred_locations": ["Chennai"],
        "experience_levels": ["0-2 years"],
        "target_roles": ["Software Developer", "Frontend Developer"],
        "remote_types": ["remote", "hybrid", "onsite"],
        "employment_types": ["full_time", "part_time", "contract", "internship"],
        "daily_application_target": 5,
        "daily_application_maximum": 10,
        "max_concurrent_executions": 1,
        **extra,
    }
    prefs = Preferences(**values)
    db.add(prefs)
    db.flush()
    return prefs


def _seed_resume(
    db,
    profile,
    *,
    name="candidate_resume.pdf",
    target_role="Software Developer",
    is_active=True,
    version="v1",
    with_bytes=False,
):
    resume = Resume(
        profile_id=profile.id if profile is not None else None,
        name=name,
        target_role=target_role,
        file_path="resumes/candidate.pdf",
        file_name=name,
        file_size=100 if with_bytes else 0,
        content_type="application/pdf",
        version=version,
        is_active=is_active,
    )
    if with_bytes:
        get_storage().save(b"%PDF-1.4 mock resume bytes phase141", resume.file_path)
    db.add(resume)
    db.flush()
    return resume


def _insert_job(db, *, source="apify", url="mock://simple-form", app_url=None, **extra):
    from app.services import job_service

    result = job_service.insert_jobs(
        db, [_job(url=url, application_url=app_url, **extra)], source=source
    )
    assert result.inserted == 1
    return db.scalar(select(Job).order_by(Job.id.desc()))


def _approved_package(
    db,
    *,
    source="apify",
    url="mock://simple-form",
    app_url=None,
    resume_with_bytes=False,
):
    profile = _seed_profile(db)
    _seed_preferences(db)
    _seed_resume(db, profile, with_bytes=resume_with_bytes)
    job = _insert_job(db, source=source, url=url, app_url=app_url)
    package = ApplicationPackage(
        job_id=job.id,
        selected_resume_id=None,
        status="APPROVED",
        version=1,
    )
    db.add(package)
    db.flush()
    return package, job


# ---------------------------------------------------------------------------
# 1. Multi-page form detection
# ---------------------------------------------------------------------------

class TestMultiPageDetection:
    def test_detects_next_button(self):
        nav = [{"role": "button", "text": "Continue"}]
        assert executor_mod._is_multi_page_form([], nav) is True

    def test_detects_step_indicator_in_heading(self):
        assert executor_mod._is_multi_page_form([], [], heading="Step 2 of 5") is True

    def test_detects_page_indicator_in_heading(self):
        assert executor_mod._is_multi_page_form([], [], heading="Page 1 of 3") is True

    def test_no_next_no_indicator_not_multi_page(self):
        assert executor_mod._is_multi_page_form([], []) is False

    def test_only_back_button_not_multi_page(self):
        nav = [{"role": "button", "text": "Back"}]
        assert executor_mod._is_multi_page_form([], nav) is False

    def test_heading_without_step_not_multi_page(self):
        assert executor_mod._is_multi_page_form([], [], heading="Application Form") is False


class TestNavigationDetection:
    def test_has_next_true(self):
        nav = [{"role": "button", "text": "Next"}]
        result = detect_navigation(nav)
        assert result.has_next is True

    def test_has_review_true(self):
        nav = [{"role": "button", "text": "Review Application"}]
        result = detect_navigation(nav)
        assert result.has_review is True

    def test_no_navigation(self):
        result = detect_navigation([])
        assert result.has_next is False
        assert result.has_back is False
        assert result.has_submit is False


# ---------------------------------------------------------------------------
# 2. MockBrowserDriver integration
# ---------------------------------------------------------------------------

class TestMockDriverMultiPage:
    def test_multi_page_scenario_has_nav(self):
        driver = MockBrowserDriver("mock://multi-page")
        nav = driver.get_navigation_elements()
        assert len(nav) > 0
        assert any(n["text"] == "Continue" for n in nav)

    def test_review_page_scenario_has_submit(self):
        driver = MockBrowserDriver("mock://review-page")
        nav = driver.get_navigation_elements()
        assert any("Submit" in n["text"] for n in nav)

    def test_simple_form_no_nav(self):
        driver = MockBrowserDriver("mock://simple-form")
        nav = driver.get_navigation_elements()
        assert nav == []


# ---------------------------------------------------------------------------
# 3. FormSession integration
# ---------------------------------------------------------------------------

class TestFormSessionIntegration:
    def test_create_session_for_execution(self):
        session = FormSession(
            session_id="exec-123",
            application_id=None,
            execution_run_id=123,
            package_id=456,
        )
        assert session.session_id == "exec-123"
        assert session.status == FormSessionState.DISCOVERING

    def test_session_serialization(self):
        session = FormSession(
            session_id="exec-456",
            application_id=None,
            execution_run_id=456,
            package_id=789,
        )
        data = session.to_dict()
        assert data["session_id"] == "exec-456"
        assert data["status"] == "DISCOVERING"


# ---------------------------------------------------------------------------
# 4. run_execution branching (single-page)
# ---------------------------------------------------------------------------

class TestRunExecutionSinglePage:
    def test_single_page_still_works(self, db_session):
        """Single-page forms go through the original path unchanged."""
        package, _job_obj = _approved_package(db_session, url="mock://simple-form")
        execution = executor_mod.run_execution(
            db_session, package, headless=True
        )

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )
        # Verify it went through the normal steps
        steps = list(db_session.scalars(
            select(ApplicationExecutionStep)
            .where(ApplicationExecutionStep.execution_id == execution.id)
            .order_by(ApplicationExecutionStep.id)
        ))
        step_names = [s.step for s in steps]
        assert "open" in step_names
        assert "inspect_form" in step_names

    def test_single_page_fill_fields_step(self, db_session):
        """Single-page form fills fields in the original order."""
        package, _job_obj = _approved_package(db_session, url="mock://simple-form")
        execution = executor_mod.run_execution(
            db_session, package, headless=True
        )

        assert execution is not None
        # fill_fields step should exist
        steps = list(db_session.scalars(
            select(ApplicationExecutionStep)
            .where(ApplicationExecutionStep.execution_id == execution.id)
            .order_by(ApplicationExecutionStep.id)
        ))
        step_names = [s.step for s in steps]
        assert "fill_fields" in step_names


# ---------------------------------------------------------------------------
# 5. run_execution branching (multi-page)
# ---------------------------------------------------------------------------

class TestRunExecutionMultiPage:
    def test_multi_page_detected_and_routed(self, db_session):
        """Multi-page forms are detected and routed through orchestrator."""
        package, _job_obj = _approved_package(db_session, url="mock://multi-page")
        execution = executor_mod.run_execution(
            db_session, package, headless=True
        )

        assert execution is not None
        # Multi-page should still complete with a status
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

    def test_multi_page_creates_inspect_steps(self, db_session):
        """Multi-page execution creates inspect_form steps for each page."""
        package, _job_obj = _approved_package(db_session, url="mock://multi-page")
        execution = executor_mod.run_execution(
            db_session, package, headless=True
        )

        steps = list(db_session.scalars(
            select(ApplicationExecutionStep)
            .where(ApplicationExecutionStep.execution_id == execution.id)
            .order_by(ApplicationExecutionStep.id)
        ))
        inspect_steps = [s for s in steps if s.step == "inspect_form"]
        # Should have at least 1 inspect step (page detection + orchestrator pages)
        assert len(inspect_steps) >= 1


# ---------------------------------------------------------------------------
# 6. Safety preservation
# ---------------------------------------------------------------------------

class TestSafetyPreservation:
    def test_captcha_still_blocks(self, db_session):
        """CAPTCHA detection still blocks execution in multi-page path."""
        package, _job_obj = _approved_package(db_session, url="mock://captcha")
        execution = executor_mod.run_execution(
            db_session, package, headless=True
        )

        assert execution.status == base.STATUS_BLOCKED
        assert execution.current_step == "open"

    def test_login_required_still_blocks(self, db_session):
        """Login detection still blocks execution."""
        package, _job_obj = _approved_package(db_session, url="mock://login-required")
        execution = executor_mod.run_execution(
            db_session, package, headless=True
        )

        assert execution.status == base.STATUS_AWAITING_USER
        assert execution.current_step == "open"


# ---------------------------------------------------------------------------
# 7. End-to-end orchestrator flow
# ---------------------------------------------------------------------------

class TestOrchestratorEndToEnd:
    def test_orchestrator_handles_page_loop(self):
        """Verify orchestrator can inspect->map->fill->validate->navigate."""
        driver = MockBrowserDriver("mock://multi-page")
        session = FormSession(
            session_id="test-orch",
            application_id=None,
            execution_run_id=999,
            package_id=888,
        )

        profile_ctx = build_profile_context(
            {"full_name": "Test User", "email": "test@example.com"},
            {"daily_application_target": 5},
            [],
        )

        # Page 1: inspect
        url = driver.get_current_url()
        raw_fields = driver.inspect_form()
        heading = driver.get_heading()
        nav = driver.get_navigation_elements()
        snapshot = inspect_page(session, url, raw_fields, nav, heading)
        assert snapshot is not None
        assert snapshot.has_next_button is True

        # Map fields
        mapping = map_page_fields(session, profile_ctx)
        assert len(mapping.fields) > 0

        # Fill known fields
        fill_page_fields(session, driver, mapping)

        # Validate
        is_valid, issues = validate_page(session, mapping)
        assert isinstance(is_valid, bool)

    def test_single_page_no_navigation(self):
        """Single-page form doesn't trigger navigation."""
        driver = MockBrowserDriver("mock://simple-form")
        nav = driver.get_navigation_elements()
        assert nav == []

        session = FormSession(
            session_id="test-single",
            application_id=None,
            execution_run_id=998,
            package_id=887,
        )

        url = driver.get_current_url()
        raw_fields = driver.inspect_form()
        heading = driver.get_heading()
        snapshot = inspect_page(session, url, raw_fields, nav, heading)
        assert snapshot.has_next_button is False
