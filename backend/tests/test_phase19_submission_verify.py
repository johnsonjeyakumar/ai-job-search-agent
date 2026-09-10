"""Phase 19 — Submission verification + application outcome intelligence tests.

Tests the submission outcome model, confirmation detection, reference ID
extraction, duplicate detection, uncertain-submission handling, and retry
policy. Uses the Phase 18 mock server + real Playwright browser.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.application_execution.submission_verify import (
    OUTCOME_TO_EXECUTION_STATUS,
    DuplicateVerdict,
    FailureType,
    SubmissionOutcome,
    check_duplicate,
    detect_confirmation,
    extract_reference_id,
    is_retryable,
    should_block_retry,
)
from tests.e2e.mock_app_server import MockApplicationServer

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — SUBMISSION OUTCOME MODEL
# ═══════════════════════════════════════════════════════════════════════════

class TestSubmissionOutcomeModel:
    def test_all_outcomes_exist(self):
        expected = {
            "SUBMIT_ATTEMPTED", "SUBMITTED", "SUBMISSION_CONFIRMED",
            "SUBMISSION_UNCERTAIN", "SUBMISSION_FAILED",
            "DUPLICATE_SUSPECTED", "BLOCKED",
        }
        actual = {o.value for o in SubmissionOutcome}
        assert expected == actual

    def test_outcome_to_execution_status_mapping(self):
        assert OUTCOME_TO_EXECUTION_STATUS[SubmissionOutcome.SUBMISSION_CONFIRMED] == "SUBMISSION_CONFIRMED"
        assert OUTCOME_TO_EXECUTION_STATUS[SubmissionOutcome.SUBMISSION_UNCERTAIN] == "SUBMISSION_UNKNOWN"
        assert OUTCOME_TO_EXECUTION_STATUS[SubmissionOutcome.SUBMISSION_FAILED] == "EXECUTION_FAILED"
        assert OUTCOME_TO_EXECUTION_STATUS[SubmissionOutcome.BLOCKED] == "BLOCKED"

    def test_failure_types_exist(self):
        expected = {
            "SUBMISSION_REJECTED", "VALIDATION_FAILURE", "AUTH_FAILURE",
            "CAPTCHA_BLOCKED", "NAVIGATION_FAILURE", "CONFIRMATION_MISSING",
            "DUPLICATE_SUSPECTED", "NETWORK_ERROR", "BROWSER_ERROR",
        }
        actual = {f.value for f in FailureType}
        assert expected == actual


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — CONFIRMATION DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class TestConfirmationDetection:
    def test_strong_confirmation_success_text(self):
        text = "Thank you for your application! Your application has been submitted successfully."
        result = detect_confirmation(text, "https://example.com/confirm", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        assert result.confidence == "STRONG"
        assert result.confirmation_type == "success_text"

    def test_strong_confirmation_with_reference_id(self):
        text = "Application submitted! Application ID: APP-12345. We will review it shortly."
        result = detect_confirmation(text, "https://example.com/done", "https://example.com/apply")
        assert result.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        assert result.confidence == "STRONG"
        assert result.confirmation_reference_id == "APP-12345"

    def test_weak_signal_only(self):
        text = "We are processing your application. Please wait for email confirmation."
        result = detect_confirmation(text, "https://example.com/status", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.SUBMITTED
        assert result.confidence == "WEAK"

    def test_no_confirmation_evidence(self):
        text = "Some random page content with no success markers."
        result = detect_confirmation(text, "https://example.com/page", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.SUBMISSION_UNCERTAIN
        assert result.confidence == "NONE"
        assert result.failure_type == FailureType.CONFIRMATION_MISSING

    def test_rejection_detected(self):
        text = "We regret to inform you that your application was not selected. The position has been filled."
        result = detect_confirmation(text, "https://example.com/status", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.SUBMISSION_FAILED
        assert result.confidence == "STRONG"
        assert result.failure_type == FailureType.SUBMISSION_REJECTED

    def test_duplicate_warning_detected(self):
        text = "You have already applied for this position. Your previous application is being reviewed."
        result = detect_confirmation(text, "https://example.com/dup", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.DUPLICATE_SUSPECTED
        assert result.confidence == "STRONG"
        assert result.failure_type == FailureType.DUPLICATE_SUSPECTED

    def test_url_change_to_confirmation_page(self):
        text = "Application received."
        result = detect_confirmation(text, "https://example.com/confirm", "https://example.com/apply")
        assert result.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        assert result.confidence == "STRONG"

    def test_url_change_only_weak(self):
        text = "Processing your request."
        result = detect_confirmation(text, "https://example.com/status", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.SUBMITTED
        assert result.confidence == "WEAK"

    def test_no_url_change_no_markers(self):
        text = "Same page content."
        result = detect_confirmation(text, "https://example.com/submit", "https://example.com/submit")
        assert result.outcome == SubmissionOutcome.SUBMISSION_UNCERTAIN

    def test_confidence_none_when_no_evidence(self):
        text = "Nothing helpful here."
        result = detect_confirmation(text, "https://example.com/x", None)
        assert result.confidence == "NONE"

    def test_observed_at_timestamp_set(self):
        result = detect_confirmation("test", "https://example.com", None)
        assert result.observed_at is not None
        assert "T" in result.observed_at

    def test_confirmation_text_extracted(self):
        text = "Thank you for your application! We received it successfully."
        result = detect_confirmation(text, "https://example.com/ok", "https://example.com/apply")
        assert len(result.confirmation_text) > 0
        assert "thank you" in result.confirmation_text.lower()


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5 — REFERENCE ID EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

class TestReferenceIdExtraction:
    def test_application_id(self):
        assert extract_reference_id("Application ID: APP-12345") == "APP-12345"

    def test_application_number(self):
        assert extract_reference_id("Application Number: 893241") == "893241"

    def test_confirmation_number(self):
        assert extract_reference_id("Confirmation Number: 482917") == "482917"

    def test_reference_id(self):
        assert extract_reference_id("Reference ID: ABC123") == "ABC123"

    def test_candidate_id(self):
        assert extract_reference_id("Candidate ID: C-456") == "C-456"

    def test_submission_id(self):
        assert extract_reference_id("Submission ID: S-789") == "S-789"

    def test_application_number_is(self):
        assert extract_reference_id("Your application number is 12345.") == "12345"

    def test_no_reference_id(self):
        assert extract_reference_id("No IDs here.") is None

    def test_empty_text(self):
        assert extract_reference_id("") is None

    def test_colon_separator(self):
        assert extract_reference_id("Application ID：APP-999") == "APP-999"

    def test_strips_trailing_punctuation(self):
        assert extract_reference_id("Reference ID: ABC123.") == "ABC123"

    def test_min_length_requirement(self):
        # Single character should not be extracted
        assert extract_reference_id("Application ID: X") is None


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 — DUPLICATE DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class TestDuplicateDetection:
    def test_safe_to_submit_no_history(self):
        result = check_duplicate(job_id=1)
        assert result.verdict == DuplicateVerdict.SAFE_TO_SUBMIT

    def test_already_applied_confirmed(self):
        result = check_duplicate(
            job_id=1,
            existing_applications=[{"id": 10, "job_id": 1, "lifecycle_status": "SUBMISSION_CONFIRMED"}],
        )
        assert result.verdict == DuplicateVerdict.ALREADY_APPLIED
        assert result.existing_application_id == 10

    def test_already_applied_submitted(self):
        result = check_duplicate(
            job_id=1,
            existing_applications=[{"id": 11, "job_id": 1, "lifecycle_status": "SUBMITTED"}],
        )
        assert result.verdict == DuplicateVerdict.ALREADY_APPLIED

    def test_duplicate_suspected_executing(self):
        result = check_duplicate(
            job_id=1,
            existing_applications=[{"id": 12, "job_id": 1, "lifecycle_status": "EXECUTING"}],
        )
        assert result.verdict == DuplicateVerdict.DUPLICATE_SUSPECTED

    def test_execution_already_submitted(self):
        result = check_duplicate(
            job_id=1,
            existing_executions=[{"id": 100, "status": "SUBMITTED"}],
        )
        assert result.verdict == DuplicateVerdict.ALREADY_APPLIED
        assert result.existing_execution_id == 100

    def test_execution_uncertain(self):
        result = check_duplicate(
            job_id=1,
            existing_executions=[{"id": 101, "status": "SUBMISSION_UNKNOWN"}],
        )
        assert result.verdict == DuplicateVerdict.DUPLICATE_SUSPECTED
        assert "uncertain" in result.reason.lower()

    def test_no_duplicate_different_job(self):
        result = check_duplicate(
            job_id=2,
            existing_applications=[{"id": 10, "job_id": 1, "lifecycle_status": "SUBMISSION_CONFIRMED"}],
        )
        assert result.verdict == DuplicateVerdict.SAFE_TO_SUBMIT

    def test_no_duplicate_different_package(self):
        result = check_duplicate(
            job_id=1,
            existing_executions=[{"id": 100, "status": "EXECUTION_READY"}],
        )
        assert result.verdict == DuplicateVerdict.SAFE_TO_SUBMIT


# ═══════════════════════════════════════════════════════════════════════════
# STEP 9 — UNCERTAIN SUBMISSION HANDLING
# ═══════════════════════════════════════════════════════════════════════════

class TestUncertainSubmission:
    def test_uncertain_outcome_blocks_retry(self):
        assert should_block_retry(SubmissionOutcome.SUBMISSION_UNCERTAIN) is True

    def test_duplicate_suspected_blocks_retry(self):
        assert should_block_retry(SubmissionOutcome.DUPLICATE_SUSPECTED) is True

    def test_blocked_blocks_retry(self):
        assert should_block_retry(SubmissionOutcome.BLOCKED) is True

    def test_confirmed_allows_future_runs(self):
        assert should_block_retry(SubmissionOutcome.SUBMISSION_CONFIRMED) is False

    def test_failed_allows_review(self):
        assert should_block_retry(SubmissionOutcome.SUBMISSION_FAILED) is False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 15 — RETRY POLICY
# ═══════════════════════════════════════════════════════════════════════════

class TestRetryPolicy:
    def test_navigation_failure_retryable_before_submit(self):
        assert is_retryable(FailureType.NAVIGATION_FAILURE, after_submit=False) is True

    def test_browser_error_retryable_before_submit(self):
        assert is_retryable(FailureType.BROWSER_ERROR, after_submit=False) is True

    def test_network_error_retryable_before_submit(self):
        assert is_retryable(FailureType.NETWORK_ERROR, after_submit=False) is True

    def test_captcha_never_retryable(self):
        assert is_retryable(FailureType.CAPTCHA_BLOCKED, after_submit=False) is False
        assert is_retryable(FailureType.CAPTCHA_BLOCKED, after_submit=True) is False

    def test_auth_failure_never_retryable(self):
        assert is_retryable(FailureType.AUTH_FAILURE, after_submit=False) is False

    def test_submission_rejected_never_retryable(self):
        assert is_retryable(FailureType.SUBMISSION_REJECTED, after_submit=False) is False

    def test_no_retry_after_submit(self):
        assert is_retryable(FailureType.NAVIGATION_FAILURE, after_submit=True) is False
        assert is_retryable(FailureType.BROWSER_ERROR, after_submit=True) is False
        assert is_retryable(FailureType.NETWORK_ERROR, after_submit=True) is False

    def test_confirmation_missing_never_retryable(self):
        assert is_retryable(FailureType.CONFIRMATION_MISSING, after_submit=False) is False
        assert is_retryable(FailureType.CONFIRMATION_MISSING, after_submit=True) is False

    def test_duplicate_never_retryable(self):
        assert is_retryable(FailureType.DUPLICATE_SUSPECTED, after_submit=False) is False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 18 — INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_detect_confirmation_from_submit_result(self):
        """Simulate what the executor does with a SubmissionResult."""
        from app.application_execution.submission_verify import detect_confirmation

        # Simulate a confirmed submission
        raw_text = (
            "Thank you for your application! "
            "Application ID: APP-2026-12345 "
            "We will review it shortly."
        )
        evidence = detect_confirmation(
            page_text=raw_text,
            current_url="https://example.com/confirm",
            previous_url="https://example.com/apply",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        assert evidence.confidence == "STRONG"
        assert evidence.confirmation_reference_id == "APP-2026-12345"

    def test_detect_confirmation_uncertain_flow(self):
        """Simulate uncertain submission — no evidence, no URL change."""
        evidence = detect_confirmation(
            page_text="Some random page content with no markers.",
            current_url="https://example.com/same-page",
            previous_url="https://example.com/same-page",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMISSION_UNCERTAIN
        assert evidence.failure_type == FailureType.CONFIRMATION_MISSING

    def test_weak_signal_with_url_change(self):
        """Weak signal + URL change = SUBMITTED (weak), not uncertain."""
        evidence = detect_confirmation(
            page_text="We are processing your request.",
            current_url="https://example.com/status",
            previous_url="https://example.com/submit",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMITTED
        assert evidence.confidence == "WEAK"

    def test_duplicate_prevents_submission(self):
        """Duplicate check prevents execution."""
        result = check_duplicate(
            job_id=42,
            existing_applications=[
                {"id": 5, "job_id": 42, "lifecycle_status": "SUBMISSION_CONFIRMED"},
            ],
        )
        assert result.verdict == DuplicateVerdict.ALREADY_APPLIED
        # Executor should block submission
        assert result.existing_application_id == 5

    def test_evidence_fields_populated(self):
        """ConfirmationEvidence has all required fields."""
        evidence = detect_confirmation(
            "Thank you! Application submitted. Reference: REF-999.",
            "https://example.com/ok",
            "https://example.com/apply",
        )
        assert evidence.outcome is not None
        assert evidence.confidence is not None
        assert evidence.confirmation_type is not None
        assert evidence.observed_at is not None
        assert isinstance(evidence.evidence_ids, list)

    def test_no_fabricated_ids(self):
        """Reference extraction never invents IDs."""
        assert extract_reference_id("No IDs here") is None
        assert extract_reference_id("") is None
        assert extract_reference_id("Application ID:") is None


# ═══════════════════════════════════════════════════════════════════════════
# REAL PLAYWRIGHT E2E (STEP 19)
# ═══════════════════════════════════════════════════════════════════════════

pytestmark_e2e = pytest.mark.e2e

try:
    from playwright.sync_api import sync_playwright
    _pw_available = True
except ImportError:
    _pw_available = False


@pytest.fixture(scope="module")
def mock_server_e2e():
    srv = MockApplicationServer(port=0)
    url = srv.start()
    yield srv, url
    srv.stop()


@pytest.fixture(scope="module")
def pw_browser_e2e():
    if not _pw_available:
        pytest.skip("Playwright not installed")
    pw = sync_playwright().start()
    br = pw.chromium.launch(headless=True)
    yield br
    br.close()
    pw.stop()


@pytest.fixture()
def page_e2e(pw_browser_e2e):
    p = pw_browser_e2e.new_page()
    p.set_default_timeout(15000)
    yield p
    p.close()


def _tmp_resume(name: str = "test_resume.pdf") -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_bytes(b"%PDF-1.4 test-content-for-e2e")
    return p


class TestPlaywrightE2EConfirmation:
    def test_confirm_with_reference_id(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/confirm-with-ref")

        from app.application_execution.browser import PlaywrightBrowserDriver
        driver = PlaywrightBrowserDriver.__new__(PlaywrightBrowserDriver)
        driver._page = page_e2e
        driver._elements = {}
        driver._resume_input = None

        result = driver.submit()
        # No submit button on confirm page — that's expected
        assert result.failure is True

    def test_detect_confirmation_on_confirm_page(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/confirm-with-ref")

        text = page_e2e.inner_text("body")
        evidence = detect_confirmation(
            page_text=text,
            current_url=f"{base}/confirm-with-ref",
            previous_url=f"{base}/apply",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        assert evidence.confidence == "STRONG"
        assert evidence.confirmation_reference_id == "APP-2026-98765"

    def test_confirm_no_reference(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/confirm-no-ref")

        text = page_e2e.inner_text("body")
        evidence = detect_confirmation(
            page_text=text,
            current_url=f"{base}/confirm-no-ref",
            previous_url=f"{base}/apply",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        assert evidence.confidence == "STRONG"
        assert evidence.confirmation_reference_id is None

    def test_uncertain_submission_page(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/uncertain-submit")

        text = page_e2e.inner_text("body")
        evidence = detect_confirmation(
            page_text=text,
            current_url=f"{base}/uncertain-submit",
            previous_url=f"{base}/submit",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMISSION_UNCERTAIN

    def test_rejection_page(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/rejected")

        text = page_e2e.inner_text("body")
        evidence = detect_confirmation(
            page_text=text,
            current_url=f"{base}/rejected",
            previous_url=f"{base}/submit",
        )
        assert evidence.outcome == SubmissionOutcome.SUBMISSION_FAILED
        assert evidence.failure_type == FailureType.SUBMISSION_REJECTED

    def test_duplicate_warning_page(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/duplicate-warning")

        text = page_e2e.inner_text("body")
        evidence = detect_confirmation(
            page_text=text,
            current_url=f"{base}/duplicate-warning",
            previous_url=f"{base}/submit",
        )
        assert evidence.outcome == SubmissionOutcome.DUPLICATE_SUSPECTED

    def test_reference_id_extraction_from_page(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/confirm-with-ref")

        text = page_e2e.inner_text("body")
        ref = extract_reference_id(text)
        assert ref == "APP-2026-98765"

    def test_reference_id_from_delayed_confirm(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/delayed-confirm")

        text = page_e2e.inner_text("body")
        ref = extract_reference_id(text)
        assert ref == "REF-2026-55555"

    def test_captcha_still_blocks(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/captcha")

        from app.application_execution.browser import PlaywrightBrowserDriver
        driver = PlaywrightBrowserDriver.__new__(PlaywrightBrowserDriver)
        driver._page = page_e2e
        driver._elements = {}
        driver._resume_input = None

        assert driver.detect_captcha() is True

    def test_auth_still_blocks(self, page_e2e, mock_server_e2e):
        srv, base = mock_server_e2e
        page_e2e.goto(f"{base}/auth-required")

        from app.application_execution.browser import PlaywrightBrowserDriver
        driver = PlaywrightBrowserDriver.__new__(PlaywrightBrowserDriver)
        driver._page = page_e2e
        driver._elements = {}
        driver._resume_input = None

        assert driver.detect_login() is True
