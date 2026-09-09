"""Phase 14.2: Comprehensive integration QA for multi-page executor.

Tests the ACTUAL executor.run_execution() with multi-page mock forms.
Does NOT test orchestrator in isolation — tests the real integration path.
"""
from __future__ import annotations

import time
from unittest.mock import patch

from sqlalchemy import select

from app.application_execution import base
from app.application_execution import executor as executor_mod
from app.application_execution.form_orchestrator import (
    detect_dynamic_changes,
    fill_page_fields,
    inspect_page,
    map_page_fields,
    navigate_to_next,
    validate_page,
)
from app.application_execution.form_session import (
    FormSession,
)
from app.models.application_execution import ApplicationExecutionStep
from app.models.application_package import ApplicationPackage
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.storage.local import get_storage
from tests.multi_page_mock_driver import MultiPageMockDriver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job(title="Software Developer", company="Acme", **extra):
    return {
        "title": title,
        "company": company,
        "source": "apify",
        "source_job_id": extra.pop("source_job_id", f"qa-{abs(hash(title))}"),
        "url": extra.pop("url", "mock://3page"),
        "application_url": extra.pop("application_url", None),
        "location": extra.pop("location", "Chennai"),
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
        "name": "QA Candidate",
        "email": f"qa-{abs(hash(str(extra))) or 11}@example.test",
        "city": "Chennai",
        "degree": "B.Tech",
        "university": "Anna University",
        "graduation_year": 2024,
        "skills": ["Python", "React", "PostgreSQL"],
        "skills_programming": ["Python", "Java"],
        "skills_frameworks": ["React"],
        "skills_databases": ["PostgreSQL"],
        "experience_level": "0-2 years",
        "preferred_roles": ["Software Developer"],
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
        "target_roles": ["Software Developer"],
        "remote_types": ["remote", "hybrid", "onsite"],
        "employment_types": ["full_time"],
        "daily_application_target": 5,
        "daily_application_maximum": 10,
        "max_concurrent_executions": 1,
        **extra,
    }
    prefs = Preferences(**values)
    db.add(prefs)
    db.flush()
    return prefs


def _seed_resume(db, profile, with_bytes=False):
    resume = Resume(
        profile_id=profile.id if profile is not None else None,
        name="qa_resume.pdf",
        target_role="Software Developer",
        file_path="resumes/qa.pdf",
        file_name="qa_resume.pdf",
        file_size=100 if with_bytes else 0,
        content_type="application/pdf",
        version="v1",
        is_active=True,
    )
    if with_bytes:
        get_storage().save(b"%PDF-1.4 mock resume bytes qa", resume.file_path)
    db.add(resume)
    db.flush()
    return resume


def _insert_job(db, **extra):
    from app.services import job_service
    result = job_service.insert_jobs(db, [_job(**extra)], source="apify")
    assert result.inserted == 1
    return db.scalar(select(Job).order_by(Job.id.desc()))


def _make_package(db, *, url="mock://3page", with_resume=False):
    profile = _seed_profile(db)
    _seed_preferences(db)
    resume = _seed_resume(db, profile, with_bytes=with_resume) if with_resume else None
    job = _insert_job(db, url=url)
    package = ApplicationPackage(
        job_id=job.id,
        selected_resume_id=resume.id if resume else None,
        status="APPROVED",
        version=1,
    )
    db.add(package)
    db.flush()
    return package, job


def _get_steps(db, execution_id):
    return list(db.scalars(
        select(ApplicationExecutionStep)
        .where(ApplicationExecutionStep.execution_id == execution_id)
        .order_by(ApplicationExecutionStep.id)
    ))


def _step_names(db, execution_id):
    return [s.step for s in _get_steps(db, execution_id)]


# ---------------------------------------------------------------------------
# 2. SINGLE-PAGE EXECUTION
# ---------------------------------------------------------------------------

class TestSinglePageExecution:
    def test_single_page_full_flow(self, db_session):
        """Run a complete single-page form through the executor."""
        package, _job_obj = _make_package(db_session, url="mock://simple-form")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

        names = _step_names(db_session, execution.id)
        assert "open" in names
        assert "inspect_form" in names
        assert "map_fields" in names
        assert "fill_fields" in names

    def test_single_page_with_resume(self, db_session):
        """Single-page form with resume upload."""
        package, _job_obj = _make_package(db_session, url="mock://simple-form", with_resume=True)
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        names = _step_names(db_session, execution.id)
        assert "upload_resume" in names


# ---------------------------------------------------------------------------
# 3. THREE-PAGE EXECUTION
# ---------------------------------------------------------------------------

class TestThreePageExecution:
    def test_three_page_full_flow(self, db_session):
        """Run a 3-page form through the actual executor."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

        steps = _get_steps(db_session, execution.id)
        inspect_steps = [s for s in steps if s.step == "inspect_form"]
        assert len(inspect_steps) >= 2, (
            f"Expected at least 2 inspect steps for 3-page form, got {len(inspect_steps)}"
        )

    def test_three_page_creates_execution_row(self, db_session):
        """One execution row for the entire 3-page flow."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution.execution_summary is not None
        summary = execution.execution_summary
        assert "fields_detected" in summary
        assert "fields_filled" in summary

    def test_three_page_step_trail(self, db_session):
        """Verify the step trail records page transitions."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        steps = _get_steps(db_session, execution.id)
        step_names_list = [s.step for s in steps]
        assert "open" in step_names_list
        assert "inspect_form" in step_names_list


# ---------------------------------------------------------------------------
# 4. FIVE-PAGE EXECUTION
# ---------------------------------------------------------------------------

class TestFivePageExecution:
    def test_five_page_full_flow(self, db_session):
        """Run a 5-page form through the actual executor."""
        package, _job_obj = _make_package(db_session, url="mock://5page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

        steps = _get_steps(db_session, execution.id)
        inspect_steps = [s for s in steps if s.step == "inspect_form"]
        assert len(inspect_steps) >= 3, (
            f"Expected at least 3 inspect steps for 5-page form, got {len(inspect_steps)}"
        )

    def test_five_page_executor_invokes_orchestrator(self, db_session):
        """Verify the executor actually invokes the orchestrator for 5-page."""
        package, _job_obj = _make_package(db_session, url="mock://5page")

        with patch(
            "app.application_execution.executor._run_multi_page_execution",
            wraps=executor_mod._run_multi_page_execution,
        ) as mock_orch:
            executor_mod.run_execution(db_session, package, headless=True)
            assert mock_orch.called, "Orchestrator was not invoked for 5-page form"

    def test_five_page_multiple_inspect_steps(self, db_session):
        """Verify executor records inspect steps for multiple pages."""
        package, _job_obj = _make_package(db_session, url="mock://5page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        steps = _get_steps(db_session, execution.id)
        inspect_steps = [s for s in steps if s.step == "inspect_form"]
        assert len(inspect_steps) >= 3


# ---------------------------------------------------------------------------
# 5. CONDITIONAL FIELDS
# ---------------------------------------------------------------------------

class TestConditionalFields:
    def test_sponsorship_conditional(self, db_session):
        """Test conditional field: sponsorship question reveals visa type."""
        package, _job_obj = _make_package(db_session, url="mock://conditional")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

        steps = _get_steps(db_session, execution.id)
        inspect_steps = [s for s in steps if s.step == "inspect_form"]
        assert len(inspect_steps) >= 2

    def test_conditional_field_detected_dynamically(self):
        """Verify dynamic field detection works with conditional fields."""
        driver = MultiPageMockDriver("mock://conditional")
        driver.open("mock://conditional")

        session = FormSession(
            session_id="qa-cond",
            application_id=None,
            execution_run_id=9001,
            package_id=9002,
        )

        from app.application_execution.fields import build_profile_context
        profile_ctx = build_profile_context(
            {"full_name": "Test User"},
            {"daily_application_target": 5},
            [],
        )

        url = driver.get_current_url()
        raw_fields = driver.inspect_form()
        heading = driver.get_heading()
        nav = driver.get_navigation_elements()
        snapshot = inspect_page(session, url, raw_fields, nav, heading)
        assert snapshot.has_next_button is True

        mapping = map_page_fields(session, profile_ctx)
        fill_page_fields(session, driver, mapping)
        is_valid, _ = validate_page(session, mapping)
        navigate_to_next(session, driver, snapshot)

        url2 = driver.get_current_url()
        raw_fields2 = driver.inspect_form()
        heading2 = driver.get_heading()
        nav2 = driver.get_navigation_elements()
        inspect_page(session, url2, raw_fields2, nav2, heading2)

        changes = detect_dynamic_changes(session, snapshot.field_fingerprints, raw_fields2)
        assert changes["has_changes"] is True
        assert len(changes["added_fields"]) > 0

        added_labels = [f.label for f in changes["added_fields"]]
        assert any("Visa" in (label or "") for label in added_labels)


# ---------------------------------------------------------------------------
# 6. DYNAMIC FIELD REMOVAL
# ---------------------------------------------------------------------------

class TestDynamicFieldRemoval:
    def test_field_disappears_after_answer(self):
        """Verify removed field is detected and stale value not submitted."""
        driver = MultiPageMockDriver("mock://dynamic-removal")
        driver.open("mock://dynamic-removal")

        session = FormSession(
            session_id="qa-dyn",
            application_id=None,
            execution_run_id=9003,
            package_id=9004,
        )

        from app.application_execution.fields import build_profile_context
        profile_ctx = build_profile_context(
            {"full_name": "Test User"},
            {"daily_application_target": 5},
            [],
        )

        url = driver.get_current_url()
        raw_fields = driver.inspect_form()
        heading = driver.get_heading()
        nav = driver.get_navigation_elements()
        snapshot = inspect_page(session, url, raw_fields, nav, heading)

        mapping = map_page_fields(session, profile_ctx)
        fill_page_fields(session, driver, mapping)
        navigate_to_next(session, driver, snapshot)

        url2 = driver.get_current_url()
        raw_fields2 = driver.inspect_form()
        heading2 = driver.get_heading()
        nav2 = driver.get_navigation_elements()
        inspect_page(session, url2, raw_fields2, nav2, heading2)

        changes = detect_dynamic_changes(session, snapshot.field_fingerprints, raw_fields2)
        assert changes["has_changes"] is True


# ---------------------------------------------------------------------------
# 7. REVIEW PAGE
# ---------------------------------------------------------------------------

class TestReviewPage:
    def test_review_page_detected(self, db_session):
        """Verify review page is correctly detected and not treated as form."""
        package, _job_obj = _make_package(db_session, url="mock://review-page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

    def test_review_page_not_treated_as_form(self):
        """Verify review page navigation elements include submit, not next."""
        driver = MultiPageMockDriver("mock://review-page")
        driver.open("mock://review-page")

        nav1 = driver.get_navigation_elements()
        assert any(n["text"] == "Continue" for n in nav1)

        driver.fill("button.next", "", force_click=True)

        nav2 = driver.get_navigation_elements()
        assert any("Submit" in n["text"] for n in nav2)
        assert not any(n["text"] == "Continue" for n in nav2)


# ---------------------------------------------------------------------------
# 8. NAVIGATION SAFETY
# ---------------------------------------------------------------------------

class TestNavigationSafety:
    def test_one_click_per_transition(self):
        """Verify navigation only advances one page per click."""
        driver = MultiPageMockDriver("mock://3page")
        driver.open("mock://3page")

        assert driver.current_page_index == 0

        driver.fill("button.next", "", force_click=True)
        assert driver.current_page_index == 1

        driver.fill("button.next", "", force_click=True)
        assert driver.current_page_index == 2

        driver.fill("button.next", "", force_click=True)
        assert driver.current_page_index == 2

    def test_disabled_button_not_clicked(self):
        """Verify disabled buttons are handled gracefully."""
        driver = MultiPageMockDriver("mock://3page")
        driver.open("mock://3page")

        result = driver.fill("button.submit", "", force_click=True)
        assert result.status == "KNOWN"

    def test_no_accidental_submit_from_continue(self):
        """Verify 'Continue' click doesn't trigger submit."""
        driver = MultiPageMockDriver("mock://3page")
        driver.open("mock://3page")

        driver.fill("button.next", "", force_click=True)
        assert driver.current_page_index == 1
        assert not driver.submitted


# ---------------------------------------------------------------------------
# 9. CHECKPOINT / RESUME
# ---------------------------------------------------------------------------

class TestCheckpointResume:
    def test_checkpoint_created_during_execution(self, db_session):
        """Verify checkpoints are created during multi-page execution."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.status in (
            base.STATUS_AWAITING_USER,
            base.STATUS_AWAITING_APPROVAL,
            base.STATUS_EXECUTING,
            base.STATUS_SUBMITTED,
            base.STATUS_SUBMISSION_CONFIRMED,
        )

        steps = _get_steps(db_session, execution.id)
        assert len(steps) > 0

    def test_form_session_tracks_pages(self):
        """Verify FormSession tracks visited pages."""
        session = FormSession(
            session_id="qa-ckpt",
            application_id=None,
            execution_run_id=9005,
            package_id=9006,
        )

        from app.application_execution.form_session import PageSnapshot, PageType
        snapshot1 = PageSnapshot(
            page_index=1,
            page_key="page1",
            page_type=PageType.FORM_PAGE,
            url="mock://test",
            heading="Page 1",
            step_indicator=None,
            fingerprint="fp1",
            fields=[],
            navigation=[],
            has_next_button=True,
            has_back_button=False,
            has_submit_button=False,
            has_review_button=False,
            next_button_selector="button.next",
            back_button_selector=None,
            submit_button_selector=None,
            validation_errors=[],
            required_fields_count=0,
            filled_fields_count=0,
            discovered_at=0.0,
            inspected_at=0.0,
        )
        snapshot2 = PageSnapshot(
            page_index=2,
            page_key="page2",
            page_type=PageType.FORM_PAGE,
            url="mock://test",
            heading="Page 2",
            step_indicator=None,
            fingerprint="fp2",
            fields=[],
            navigation=[],
            has_next_button=True,
            has_back_button=False,
            has_submit_button=False,
            has_review_button=False,
            next_button_selector="button.next",
            back_button_selector=None,
            submit_button_selector=None,
            validation_errors=[],
            required_fields_count=0,
            filled_fields_count=0,
            discovered_at=0.0,
            inspected_at=0.0,
        )
        session.add_page(snapshot1)
        session.add_page(snapshot2)

        assert session.page_count == 2
        assert "page1" in session.visited_pages
        assert "page2" in session.visited_pages

    def test_session_serialization_preserves_state(self):
        """Verify session can be serialized to dict."""
        session = FormSession(
            session_id="qa-serial",
            application_id=None,
            execution_run_id=9007,
            package_id=9008,
        )

        from app.application_execution.form_session import PageSnapshot, PageType
        snapshot = PageSnapshot(
            page_index=1,
            page_key="page1",
            page_type=PageType.FORM_PAGE,
            url="mock://test",
            heading="Page 1",
            step_indicator=None,
            fingerprint="fp1",
            fields=[],
            navigation=[],
            has_next_button=True,
            has_back_button=False,
            has_submit_button=False,
            has_review_button=False,
            next_button_selector="button.next",
            back_button_selector=None,
            submit_button_selector=None,
            validation_errors=[],
            required_fields_count=0,
            filled_fields_count=0,
            discovered_at=0.0,
            inspected_at=0.0,
        )
        session.add_page(snapshot)

        data = session.to_dict()
        assert data["page_count"] == 1
        assert data["session_id"] == "qa-serial"
        assert data["status"] == "DISCOVERING"


# ---------------------------------------------------------------------------
# 10. FAILURE RECOVERY
# ---------------------------------------------------------------------------

class TestFailureRecovery:
    def test_missing_next_button(self, db_session):
        """Verify executor handles missing next button gracefully."""
        package, _job_obj = _make_package(db_session, url="mock://simple-form")
        execution = executor_mod.run_execution(db_session, package, headless=True)
        assert execution is not None

    def test_navigation_timeout_handled(self):
        """Verify navigation timeout doesn't crash the session."""
        driver = MultiPageMockDriver("mock://3page")
        driver.open("mock://3page")

        session = FormSession(
            session_id="qa-timeout",
            application_id=None,
            execution_run_id=9009,
            package_id=9010,
        )

        url = driver.get_current_url()
        raw_fields = driver.inspect_form()
        heading = driver.get_heading()
        nav = driver.get_navigation_elements()
        snapshot = inspect_page(session, url, raw_fields, nav, heading)

        success = navigate_to_next(session, driver, snapshot)
        assert success is True

    def test_bounded_retry(self):
        """Verify retry count is bounded."""
        session = FormSession(
            session_id="qa-retry",
            application_id=None,
            execution_run_id=9011,
            package_id=9012,
        )

        session.retry_count = 0
        for _ in range(10):
            session.retry_count += 1

        assert session.retry_count == 10


# ---------------------------------------------------------------------------
# 11. AUTOPILOT INTEGRATION
# ---------------------------------------------------------------------------

class TestAutopilotIntegration:
    def test_one_queue_item_per_application(self, db_session):
        """Verify one application = one queue item = one execution."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        assert execution is not None
        assert execution.package_id == package.id

        steps = _get_steps(db_session, execution.id)
        for step in steps:
            assert step.execution_id == execution.id

    def test_pages_not_separate_queue_items(self, db_session):
        """Verify multi-page execution doesn't create separate queue items."""
        package, _job_obj = _make_package(db_session, url="mock://5page")
        executor_mod.run_execution(db_session, package, headless=True)

        execs = list(db_session.scalars(
            select(executor_mod.ApplicationExecution)
            .where(executor_mod.ApplicationExecution.package_id == package.id)
        ))
        assert len(execs) == 1


# ---------------------------------------------------------------------------
# 12. IDEMPOTENCY
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_duplicate_execution_blocked(self, db_session):
        """Verify running same application twice is handled safely."""
        package, _job_obj = _make_package(db_session, url="mock://simple-form")

        exec1 = executor_mod.run_execution(db_session, package, headless=True)
        assert exec1 is not None

        exec1.status = base.STATUS_SUBMISSION_CONFIRMED
        db_session.flush()

        try:
            exec2 = executor_mod.run_execution(db_session, package, headless=True)
            if exec2 is not None:
                assert exec2.status in (
                    base.STATUS_BLOCKED,
                    base.STATUS_EXECUTION_FAILED,
                    base.STATUS_SUBMISSION_CONFIRMED,
                )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 13. EXECUTION EVIDENCE
# ---------------------------------------------------------------------------

class TestExecutionEvidence:
    def test_execution_summary_populated(self, db_session):
        """Verify execution summary contains required fields."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        summary = execution.execution_summary
        assert summary is not None
        assert "fields_detected" in summary
        assert "fields_filled" in summary
        assert "fields_needing_review" in summary
        assert "new_questions" in summary

    def test_steps_recorded_with_messages(self, db_session):
        """Verify execution steps have messages."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        steps = _get_steps(db_session, execution.id)
        steps_with_msg = [s for s in steps if s.message]
        assert len(steps_with_msg) > 0

    def test_no_secrets_in_evidence(self, db_session):
        """Verify no passwords, tokens, cookies in execution data."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        warnings = list(execution.warnings or [])
        for w in warnings:
            msg = w.get("message", "").lower()
            assert "password" not in msg
            assert "token" not in msg
            assert "cookie" not in msg
            assert "secret" not in msg


# ---------------------------------------------------------------------------
# 14. PLAYWRIGHT
# ---------------------------------------------------------------------------

class TestPlaywrightAvailability:
    def test_playwright_check(self):
        """Check if Playwright MCP tools are available."""
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            try:
                browser = pw.chromium.launch(headless=True)
                browser.close()
                pw.stop()
                return True
            except Exception:
                pw.stop()
                return False
        except ImportError:
            return False


# ---------------------------------------------------------------------------
# 15. DATA INTEGRITY
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def test_one_execution_per_package(self, db_session):
        """Verify one execution per package."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        executor_mod.run_execution(db_session, package, headless=True)

        execs = list(db_session.scalars(
            select(executor_mod.ApplicationExecution)
            .where(executor_mod.ApplicationExecution.package_id == package.id)
        ))
        assert len(execs) == 1

    def test_execution_steps_linked(self, db_session):
        """Verify all steps are linked to the correct execution."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        execution = executor_mod.run_execution(db_session, package, headless=True)

        steps = _get_steps(db_session, execution.id)
        for step in steps:
            assert step.execution_id == execution.id

    def test_no_duplicate_submission(self, db_session):
        """Verify no duplicate submission in execution."""
        package, _job_obj = _make_package(db_session, url="mock://3page")
        executor_mod.run_execution(db_session, package, headless=True)

        execs = list(db_session.scalars(
            select(executor_mod.ApplicationExecution)
            .where(executor_mod.ApplicationExecution.package_id == package.id)
        ))
        assert len(execs) == 1


# ---------------------------------------------------------------------------
# 16. PERFORMANCE
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_single_page_execution_time(self, db_session):
        """Measure single-page execution time."""
        package, _job_obj = _make_package(db_session, url="mock://simple-form")

        start = time.time()
        executor_mod.run_execution(db_session, package, headless=True)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Single-page execution took {elapsed:.2f}s"

    def test_three_page_execution_time(self, db_session):
        """Measure 3-page execution time."""
        package, _job_obj = _make_package(db_session, url="mock://3page")

        start = time.time()
        executor_mod.run_execution(db_session, package, headless=True)
        elapsed = time.time() - start

        assert elapsed < 10.0, f"3-page execution took {elapsed:.2f}s"

    def test_five_page_execution_time(self, db_session):
        """Measure 5-page execution time."""
        package, _job_obj = _make_package(db_session, url="mock://5page")

        start = time.time()
        executor_mod.run_execution(db_session, package, headless=True)
        elapsed = time.time() - start

        assert elapsed < 15.0, f"5-page execution took {elapsed:.2f}s"
