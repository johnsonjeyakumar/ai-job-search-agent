"""Phase 20 — Job expiration + preflight hardening tests.

Tests job availability detection, deadline handling, stale listing detection,
identity validation, package validation, profile validation, duplicate
integration, and preflight result model.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.application_execution.preflight import (
    JobAvailability,
    ReasonCode,
    availability_from_freshness,
    check_deadline,
    detect_listing_availability,
    run_preflight_checks,
    validate_job_identity,
    validate_package,
    validate_profile,
)
from tests.e2e.mock_app_server import MockApplicationServer

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — JOB AVAILABILITY MODEL
# ═══════════════════════════════════════════════════════════════════════════

class TestJobAvailabilityModel:
    def test_all_outcomes_exist(self):
        expected = {"ACTIVE", "EXPIRING_SOON", "EXPIRED", "CLOSED", "REMOVED", "UNAVAILABLE", "UNKNOWN"}
        actual = {a.value for a in JobAvailability}
        assert expected == actual

    def test_all_reason_codes_exist(self):
        expected = {
            "JOB_EXPIRED", "JOB_CLOSED", "JOB_REMOVED", "JOB_UNAVAILABLE",
            "JOB_STATE_UNKNOWN", "JOB_MISMATCH", "JOB_NOT_FOUND",
            "DEADLINE_PASSED", "DEADLINE_EXPIRING_SOON",
            "DUPLICATE_APPLICATION", "DUPLICATE_SUSPECTED",
            "PACKAGE_MISSING", "PACKAGE_INVALID", "PACKAGE_NOT_APPROVED",
            "RESUME_MISSING", "REQUIRED_DOCUMENT_MISSING",
            "PROFILE_INCOMPLETE", "SENSITIVE_VALUE_UNKNOWN",
            "APPLICATION_URL_MISSING", "PLATFORM_UNSUPPORTED",
            "COMPANY_MISMATCH", "TITLE_MISMATCH", "URL_MISMATCH",
            "CAPTCHA_DETECTED", "AUTH_REQUIRED",
        }
        actual = {r.value for r in ReasonCode}
        assert expected == actual


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3-4 — LISTING AVAILABILITY DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class TestListingAvailability:
    def test_active_listing(self):
        text = "We are hiring! Apply now for this exciting opportunity."
        assert detect_listing_availability(text) == JobAvailability.ACTIVE

    def test_closed_listing(self):
        text = "This position has been filled. We are no longer accepting applications."
        assert detect_listing_availability(text) == JobAvailability.CLOSED

    def test_removed_listing_404(self):
        assert detect_listing_availability("Not Found", http_status=404) == JobAvailability.REMOVED

    def test_removed_listing_410(self):
        assert detect_listing_availability("Gone", http_status=410) == JobAvailability.REMOVED

    def test_unavailable_403(self):
        assert detect_listing_availability("Forbidden", http_status=403) == JobAvailability.UNAVAILABLE

    def test_server_error_unknown(self):
        assert detect_listing_availability("Error", http_status=500) == JobAvailability.UNKNOWN

    def test_closed_text_in_page(self):
        text = "This job has been closed."
        assert detect_listing_availability(text) == JobAvailability.CLOSED

    def test_expired_text_in_page(self):
        text = "This job posting has expired."
        assert detect_listing_availability(text) == JobAvailability.CLOSED

    def test_removed_text_in_page(self):
        text = "This job has been removed."
        assert detect_listing_availability(text) == JobAvailability.REMOVED

    def test_no_markers_active(self):
        text = "Join our team! Great benefits and competitive salary."
        assert detect_listing_availability(text) == JobAvailability.ACTIVE

    def test_empty_text_active(self):
        assert detect_listing_availability("") == JobAvailability.ACTIVE


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 — DEADLINE HANDLING
# ═══════════════════════════════════════════════════════════════════════════

class TestDeadlineHandling:
    def test_no_deadline_always_valid(self):
        valid, code = check_deadline(None)
        assert valid is True
        assert code is None

    def test_future_deadline_valid(self):
        deadline = date.today() + timedelta(days=30)
        valid, code = check_deadline(deadline)
        assert valid is True
        assert code is None

    def test_past_deadline_invalid(self):
        deadline = date.today() - timedelta(days=1)
        valid, code = check_deadline(deadline)
        assert valid is False
        assert code == ReasonCode.DEADLINE_PASSED.value

    def test_deadline_today_valid(self):
        deadline = date.today()
        valid, code = check_deadline(deadline)
        assert valid is True

    def test_expiring_soon(self):
        deadline = date.today() + timedelta(days=2)
        valid, code = check_deadline(deadline, expiring_soon_days=3)
        assert valid is True
        assert code == ReasonCode.DEADLINE_EXPIRING_SOON.value

    def test_expiring_soon_threshold(self):
        deadline = date.today() + timedelta(days=5)
        valid, code = check_deadline(deadline, expiring_soon_days=3)
        assert valid is True
        assert code is None

    def test_datetime_deadline(self):
        deadline = datetime.now(timezone.utc) + timedelta(days=10)
        valid, code = check_deadline(deadline)
        assert valid is True

    def test_past_datetime_deadline(self):
        deadline = datetime.now(timezone.utc) - timedelta(days=1)
        valid, code = check_deadline(deadline)
        assert valid is False
        assert code == ReasonCode.DEADLINE_PASSED.value


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 — FRESHNESS TO AVAILABILITY MAPPING
# ═══════════════════════════════════════════════════════════════════════════

class TestFreshnessMapping:
    def test_very_fresh_active(self):
        assert availability_from_freshness("VERY_FRESH") == JobAvailability.ACTIVE

    def test_fresh_active(self):
        assert availability_from_freshness("FRESH") == JobAvailability.ACTIVE

    def test_recent_active(self):
        assert availability_from_freshness("RECENT") == JobAvailability.ACTIVE

    def test_aging_expiring(self):
        assert availability_from_freshness("AGING") == JobAvailability.EXPIRING_SOON

    def test_stale_expired(self):
        assert availability_from_freshness("STALE") == JobAvailability.EXPIRED

    def test_unknown_maps_to_unknown(self):
        assert availability_from_freshness("UNKNOWN") == JobAvailability.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# STEP 7-8 — JOB IDENTITY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class TestJobIdentity:
    def test_same_identity_valid(self):
        valid, mismatches = validate_job_identity(
            original_company="TechCorp",
            original_title="Software Engineer",
            current_company="TechCorp",
            current_title="Software Engineer",
        )
        assert valid is True
        assert mismatches == []

    def test_company_mismatch(self):
        valid, mismatches = validate_job_identity(
            original_company="TechCorp",
            original_title="Software Engineer",
            current_company="OtherCorp",
            current_title="Software Engineer",
        )
        assert valid is False
        assert ReasonCode.COMPANY_MISMATCH.value in mismatches

    def test_title_mismatch(self):
        valid, mismatches = validate_job_identity(
            original_company="TechCorp",
            original_title="Software Engineer",
            current_company="TechCorp",
            current_title="Sales Manager",
        )
        assert valid is False
        assert ReasonCode.TITLE_MISMATCH.value in mismatches

    def test_both_mismatch(self):
        valid, mismatches = validate_job_identity(
            original_company="TechCorp",
            original_title="Software Engineer",
            current_company="OtherCorp",
            current_title="Sales Manager",
        )
        assert valid is False
        assert len(mismatches) == 2

    def test_case_insensitive_comparison(self):
        valid, _ = validate_job_identity(
            original_company="TechCorp",
            original_title="Software Engineer",
            current_company="techcorp",
            current_title="software engineer",
        )
        assert valid is True

    def test_whitespace_normalization(self):
        valid, _ = validate_job_identity(
            original_company="  Tech  Corp  ",
            original_title="Software  Engineer",
            current_company="Tech Corp",
            current_title="Software Engineer",
        )
        assert valid is True

    def test_no_original_data(self):
        valid, mismatches = validate_job_identity(
            current_company="TechCorp",
            current_title="Software Engineer",
        )
        assert valid is True
        assert mismatches == []

    def test_url_change_with_identity_change(self):
        valid, mismatches = validate_job_identity(
            original_company="TechCorp",
            original_title="Software Engineer",
            original_url="https://example.com/jobs/123",
            current_company="OtherCorp",
            current_title="Sales Manager",
            current_url="https://example.com/jobs/456",
        )
        assert valid is False
        assert ReasonCode.URL_MISMATCH.value in mismatches


# ═══════════════════════════════════════════════════════════════════════════
# STEP 9 — PACKAGE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class TestPackageValidation:
    def test_valid_package(self):
        valid, issues = validate_package(
            package_status="APPROVED",
            selected_resume_id=1,
            resume_exists=True,
        )
        assert valid is True
        assert issues == []

    def test_missing_package(self):
        valid, issues = validate_package(package_status=None)
        assert valid is False
        assert ReasonCode.PACKAGE_MISSING.value in issues

    def test_not_approved(self):
        valid, issues = validate_package(
            package_status="DRAFT",
            selected_resume_id=1,
        )
        assert valid is False
        assert ReasonCode.PACKAGE_NOT_APPROVED.value in issues

    def test_quality_gate_fail(self):
        valid, issues = validate_package(
            package_status="APPROVED",
            quality_gate="FAIL",
            selected_resume_id=1,
        )
        assert valid is False
        assert ReasonCode.PACKAGE_INVALID.value in issues

    def test_missing_resume(self):
        valid, issues = validate_package(
            package_status="APPROVED",
            selected_resume_id=None,
        )
        assert valid is False
        assert ReasonCode.RESUME_MISSING.value in issues

    def test_resume_not_found(self):
        valid, issues = validate_package(
            package_status="APPROVED",
            selected_resume_id=1,
            resume_exists=False,
        )
        assert valid is False
        assert ReasonCode.RESUME_MISSING.value in issues

    def test_not_ready(self):
        valid, issues = validate_package(
            package_status="APPROVED",
            selected_resume_id=1,
            readiness="NOT_READY",
        )
        assert valid is False
        assert ReasonCode.PACKAGE_INVALID.value in issues


# ═══════════════════════════════════════════════════════════════════════════
# STEP 10 — PROFILE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileValidation:
    def test_valid_profile(self):
        valid, issues = validate_profile({"name": "John", "email": "john@example.com"})
        assert valid is True
        assert issues == []

    def test_missing_profile(self):
        valid, issues = validate_profile(None)
        assert valid is False
        assert ReasonCode.PROFILE_INCOMPLETE.value in issues

    def test_missing_name(self):
        valid, issues = validate_profile({"email": "john@example.com"})
        assert valid is False
        assert ReasonCode.PROFILE_INCOMPLETE.value in issues

    def test_missing_email(self):
        valid, issues = validate_profile({"name": "John"})
        assert valid is False
        assert ReasonCode.PROFILE_INCOMPLETE.value in issues

    def test_empty_name(self):
        valid, issues = validate_profile({"name": "", "email": "john@example.com"})
        assert valid is False

    def test_whitespace_name(self):
        valid, issues = validate_profile({"name": "   ", "email": "john@example.com"})
        assert valid is False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 13 — PREFLIGHT RESULT MODEL
# ═══════════════════════════════════════════════════════════════════════════

class TestPreflightResult:
    def test_all_checks_pass(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            package_status="APPROVED",
            selected_resume_id=1,
            resume_exists=True,
            profile_data={"name": "John", "email": "john@example.com"},
            application_url="https://example.com/apply",
        )
        assert result.eligible is True
        assert result.blocked is False
        assert result.reason_codes == []

    def test_expired_job_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.EXPIRED,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.JOB_EXPIRED.value in result.reason_codes

    def test_closed_job_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.CLOSED,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.JOB_CLOSED.value in result.reason_codes

    def test_removed_job_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.REMOVED,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.JOB_REMOVED.value in result.reason_codes

    def test_unknown_state_needs_review(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.UNKNOWN,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.needs_review is True
        assert ReasonCode.JOB_STATE_UNKNOWN.value in result.reason_codes

    def test_company_mismatch_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            job_company="OtherCorp",
            original_company="TechCorp",
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.COMPANY_MISMATCH.value in result.reason_codes

    def test_duplicate_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            duplicate_status="ALREADY_APPLIED",
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.DUPLICATE_APPLICATION.value in result.reason_codes

    def test_duplicate_suspected_needs_review(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            duplicate_status="DUPLICATE_SUSPECTED",
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.needs_review is True
        assert ReasonCode.DUPLICATE_SUSPECTED.value in result.reason_codes

    def test_missing_package_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True

    def test_missing_resume_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            package_status="APPROVED",
            selected_resume_id=None,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.RESUME_MISSING.value in result.reason_codes

    def test_profile_incomplete_needs_review(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            package_status="APPROVED",
            selected_resume_id=1,
            resume_exists=True,
            profile_data=None,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.needs_review is True
        assert ReasonCode.PROFILE_INCOMPLETE.value in result.reason_codes

    def test_deadline_passed_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            application_deadline=date.today() - timedelta(days=1),
            package_status="APPROVED",
            selected_resume_id=1,
            profile_data={"name": "John", "email": "j@x.com"},
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert ReasonCode.DEADLINE_PASSED.value in result.reason_codes

    def test_expiring_soon_needs_review(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            application_deadline=date.today() + timedelta(days=2),
            package_status="APPROVED",
            selected_resume_id=1,
            profile_data={"name": "John", "email": "j@x.com"},
            application_url="https://example.com/apply",
        )
        assert result.eligible is True
        assert result.needs_review is True
        assert ReasonCode.DEADLINE_EXPIRING_SOON.value in result.reason_codes

    def test_captcha_detected_blocks(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            captcha_detected=True,
            application_url="https://example.com/apply",
        )
        assert result.eligible is False
        assert result.has_blockers is True
        assert ReasonCode.CAPTCHA_DETECTED.value in result.reason_codes

    def test_checked_at_timestamp(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.ACTIVE,
            application_url="https://example.com/apply",
        )
        assert result.checked_at is not None
        assert "T" in result.checked_at

    def test_multiple_failures(self):
        result = run_preflight_checks(
            job_availability=JobAvailability.EXPIRED,
            duplicate_status="ALREADY_APPLIED",
            captcha_detected=True,
        )
        assert result.eligible is False
        assert len(result.reason_codes) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# STEP 19 — PLAYWRIGHT E2E
# ═══════════════════════════════════════════════════════════════════════════

try:
    from playwright.sync_api import sync_playwright
    _pw_available = True
except ImportError:
    _pw_available = False


@pytest.fixture(scope="module")
def mock_server_e20():
    srv = MockApplicationServer(port=0)
    url = srv.start()
    yield srv, url
    srv.stop()


@pytest.fixture(scope="module")
def pw_browser_e20():
    if not _pw_available:
        pytest.skip("Playwright not installed")
    pw = sync_playwright().start()
    br = pw.chromium.launch(headless=True)
    yield br
    br.close()
    pw.stop()


@pytest.fixture()
def page_e20(pw_browser_e20):
    p = pw_browser_e20.new_page()
    p.set_default_timeout(15000)
    yield p
    p.close()


class TestPlaywrightE2E:
    def test_active_job_listing(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/job-active")
        text = page_e20.inner_text("body")
        availability = detect_listing_availability(text)
        assert availability == JobAvailability.ACTIVE

    def test_closed_job_listing(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/job-closed")
        text = page_e20.inner_text("body")
        availability = detect_listing_availability(text)
        assert availability == JobAvailability.CLOSED

    def test_removed_job_listing(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        resp = page_e20.goto(f"{base}/job-removed")
        text = page_e20.inner_text("body")
        availability = detect_listing_availability(text, http_status=resp.status)
        assert availability == JobAvailability.REMOVED

    def test_expired_deadline_listing(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/job-expired-deadline")
        text = page_e20.inner_text("body")
        availability = detect_listing_availability(text)
        assert availability == JobAvailability.CLOSED

    def test_active_job_preflight_passes(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/job-active")
        text = page_e20.inner_text("body")
        availability = detect_listing_availability(text)
        result = run_preflight_checks(
            job_availability=availability,
            package_status="APPROVED",
            selected_resume_id=1,
            resume_exists=True,
            profile_data={"name": "Test", "email": "test@example.com"},
            application_url=f"{base}/job-active",
        )
        assert result.eligible is True

    def test_closed_job_preflight_blocks(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/job-closed")
        text = page_e20.inner_text("body")
        availability = detect_listing_availability(text)
        result = run_preflight_checks(
            job_availability=availability,
            application_url=f"{base}/job-closed",
        )
        assert result.eligible is False
        assert result.has_blockers is True

    def test_captcha_still_blocks(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/captcha")
        from app.application_execution.browser import PlaywrightBrowserDriver
        driver = PlaywrightBrowserDriver.__new__(PlaywrightBrowserDriver)
        driver._page = page_e20
        driver._elements = {}
        driver._resume_input = None
        assert driver.detect_captcha() is True

    def test_auth_still_blocks(self, page_e20, mock_server_e20):
        srv, base = mock_server_e20
        page_e20.goto(f"{base}/auth-required")
        from app.application_execution.browser import PlaywrightBrowserDriver
        driver = PlaywrightBrowserDriver.__new__(PlaywrightBrowserDriver)
        driver._page = page_e20
        driver._elements = {}
        driver._resume_input = None
        assert driver.detect_login() is True
