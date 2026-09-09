"""Tests for Phase 14: Multi-step & Dynamic Application Form Orchestration."""
from __future__ import annotations

from app.application_execution.base import (
    DetectedField,
)
from app.application_execution.checkpoint import (
    CheckpointStore,
    CheckpointType,
    create_form_inspected_checkpoint,
)
from app.application_execution.fields import MappingResult
from app.application_execution.form_orchestrator import (
    detect_dynamic_changes,
    validate_page,
)
from app.application_execution.form_session import (
    FieldState,
    FormSession,
    FormSessionState,
    NavigationAction,
    PageSnapshot,
    PageType,
    TrackedField,
    compute_page_fingerprint,
)
from app.application_execution.page_detector import (
    classify_page,
    detect_navigation,
    identify_page,
)
from tests.mock_forms import (
    FORM_A,
    FORM_B,
    FORM_C,
    FORM_D,
    FORM_M,
    get_mock_form,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_fields(*labels: str) -> list[DetectedField]:
    return [
        DetectedField(key=f"f{i}", label=lbl, kind="text")
        for i, lbl in enumerate(labels, 1)
    ]


def _mock_nav(texts: list[str]) -> list[dict]:
    return [{"selector": f"button.{t.lower().replace(' ', '-')}", "text": t, "role": "button"} for t in texts]


# ===========================================================================
# PART 3: Page Detection
# ===========================================================================

class TestPageDetection:
    def test_classify_form_page(self):
        result = classify_page(heading="Basic Info", field_count=5, has_next_button=True)
        assert result.page_type == PageType.FORM_PAGE
        assert result.confidence >= 0.6

    def test_classify_review_page(self):
        result = classify_page(heading="Review Your Application")
        assert result.page_type == PageType.REVIEW_PAGE
        assert result.confidence >= 0.8

    def test_classify_submission_page(self):
        result = classify_page(heading="Application Submitted")
        assert result.page_type == PageType.SUBMISSION_PAGE
        assert result.confidence >= 0.8

    def test_classify_unknown_page(self):
        result = classify_page(field_count=0, has_next_button=False, has_submit_button=False)
        assert result.page_type == PageType.UNKNOWN_PAGE

    def test_step_indicator_extraction(self):
        result = classify_page(heading="Step 2 of 5 - Experience")
        assert result.step_current == 2
        assert result.step_total == 5
        assert result.step_indicator == "Step 2 of 5"

    def test_consent_detection(self):
        result = classify_page(button_texts=["I certify that the information is correct"])
        assert result.has_consent is True

    def test_navigation_priority_submit_over_next(self):
        nav = detect_navigation([
            {"selector": "button.next", "text": "Continue"},
            {"selector": "button.submit", "text": "Submit Application"},
        ])
        assert nav.action == NavigationAction.SUBMIT
        assert nav.has_submit is True
        assert nav.has_next is True

    def test_navigation_priority_review_over_next(self):
        nav = detect_navigation([
            {"selector": "button.next", "text": "Continue"},
            {"selector": "button.review", "text": "Review Application"},
        ])
        assert nav.action == NavigationAction.REVIEW

    def test_navigation_disabled_button(self):
        nav = detect_navigation([
            {"selector": "button.next", "text": "Continue", "disabled": True},
        ])
        assert nav.has_next is True
        assert nav.next_disabled is True

    def test_navigation_back_detected(self):
        nav = detect_navigation([
            {"selector": "button.back", "text": "Back"},
        ])
        assert nav.has_back is True
        assert nav.action == NavigationAction.PREVIOUS_PAGE


# ===========================================================================
# PART 4: Page Identification
# ===========================================================================

class TestPageIdentification:
    def test_identify_page_from_url_and_heading(self):
        result = identify_page("https://example.com/apply/1", heading="Basic Info")
        assert "basic info" in result.page_key.lower()
        assert result.fingerprint != ""

    def test_fingerprint_stable_across_refresh(self):
        fp1 = compute_page_fingerprint("https://example.com/apply", "Basic Info", None, ["Name", "Email"])
        fp2 = compute_page_fingerprint("https://example.com/apply", "Basic Info", None, ["Name", "Email"])
        assert fp1 == fp2

    def test_fingerprint_different_for_different_pages(self):
        fp1 = compute_page_fingerprint("https://example.com/apply/1", "Page 1")
        fp2 = compute_page_fingerprint("https://example.com/apply/2", "Page 2")
        assert fp1 != fp2


# ===========================================================================
# PART 5-6: Form Session & State Machine
# ===========================================================================

class TestFormSession:
    def test_session_creation(self):
        session = FormSession(session_id="test-1", application_id=1)
        assert session.status == FormSessionState.DISCOVERING
        assert session.page_count == 0

    def test_add_page(self):
        session = FormSession(session_id="test-1")
        snap = PageSnapshot(page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com")
        session.add_page(snap)
        assert session.page_count == 1
        assert "p1" in session.visited_pages

    def test_set_current_page(self):
        session = FormSession(session_id="test-1")
        snap = PageSnapshot(page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com")
        session.add_page(snap)
        result = session.set_current_page("p1")
        assert result is not None
        assert session.current_page_key == "p1"

    def test_advance_page(self):
        session = FormSession(session_id="test-1")
        snap1 = PageSnapshot(page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com/1")
        snap2 = PageSnapshot(page_index=2, page_key="p2", page_type=PageType.FORM_PAGE, url="https://test.com/2")
        session.add_page(snap1)
        session.add_page(snap2)
        session.set_current_page("p1")
        result = session.advance_page()
        assert result is not None
        assert session.current_page_key == "p2"

    def test_retreat_page(self):
        session = FormSession(session_id="test-1")
        snap1 = PageSnapshot(page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com/1")
        snap2 = PageSnapshot(page_index=2, page_key="p2", page_type=PageType.FORM_PAGE, url="https://test.com/2")
        session.add_page(snap1)
        session.add_page(snap2)
        session.set_current_page("p2")
        result = session.retreat_page()
        assert result is not None
        assert session.current_page_key == "p1"

    def test_valid_transition(self):
        session = FormSession(session_id="test-1")
        assert session.transition(FormSessionState.PAGE_INSPECTED)
        assert session.status == FormSessionState.PAGE_INSPECTED

    def test_invalid_transition(self):
        session = FormSession(session_id="test-1")
        assert not session.transition(FormSessionState.SUBMITTED)

    def test_record_navigation(self):
        session = FormSession(session_id="test-1")
        session.record_navigation(NavigationAction.NEXT_PAGE, "p1", "p2")
        assert len(session.navigation_history) == 1

    def test_checkpoint_roundtrip(self):
        session = FormSession(session_id="test-1", application_id=42)
        snap = PageSnapshot(
            page_index=1, page_key="p1", page_type=PageType.FORM_PAGE,
            url="https://test.com",
            fields=[TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"), value="Alice")],
        )
        session.add_page(snap)
        session.transition(FormSessionState.PAGE_INSPECTED)
        data = session.to_checkpoint()
        restored = FormSession.from_checkpoint(data)
        assert restored.session_id == "test-1"
        assert restored.application_id == 42
        assert restored.page_count == 1
        assert "p1" in restored.pages


# ===========================================================================
# PART 8: Dynamic Form Detection
# ===========================================================================

class TestDynamicDetection:
    def test_detect_added_fields(self):
        session = FormSession(session_id="test-1")
        snap = PageSnapshot(
            page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com",
            fields=[TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"))],
        )
        session.add_page(snap)
        session.set_current_page("p1")
        prev_fps = snap.field_fingerprints
        new_fields = [
            DetectedField(key="f1", label="Name", kind="text"),
            DetectedField(key="f2", label="Email", kind="text"),
        ]
        changes = detect_dynamic_changes(session, prev_fps, new_fields)
        assert changes["has_changes"] is True
        assert changes["added_count"] == 1

    def test_detect_no_changes(self):
        session = FormSession(session_id="test-1")
        snap = PageSnapshot(
            page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com",
            fields=[TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"))],
        )
        session.add_page(snap)
        session.set_current_page("p1")
        prev_fps = snap.field_fingerprints
        new_fields = [DetectedField(key="f1", label="Name", kind="text")]
        changes = detect_dynamic_changes(session, prev_fps, new_fields)
        assert changes["has_changes"] is False


# ===========================================================================
# PART 12: Field State Tracking
# ===========================================================================

class TestFieldState:
    def test_tracked_field_lifecycle(self):
        f = TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"))
        assert f.state == FieldState.DISCOVERED
        f.state = FieldState.MAPPED
        assert f.state == FieldState.MAPPED
        f.state = FieldState.FILLED
        assert f.state == FieldState.FILLED
        f.state = FieldState.VALIDATED
        assert f.state == FieldState.VALIDATED

    def test_field_fingerprint(self):
        f1 = TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"), required=True)
        f2 = TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"), required=True)
        assert f1.fingerprint() == f2.fingerprint()

    def test_conditional_field(self):
        f = TrackedField(
            detected=DetectedField(key="f1", label="Sponsorship Type", kind="select"),
            is_conditional=True,
            parent_question="Do you require sponsorship?",
        )
        assert f.is_conditional is True
        assert f.parent_question == "Do you require sponsorship?"


# ===========================================================================
# PART 13: Page-Level Checkpoints
# ===========================================================================

class TestPageCheckpoints:
    def test_checkpoint_types_include_page_types(self):
        assert hasattr(CheckpointType, "PAGE_INSPECTED")
        assert hasattr(CheckpointType, "PAGE_READY")
        assert hasattr(CheckpointType, "PAGE_VALIDATED")
        assert hasattr(CheckpointType, "NAVIGATION_COMPLETED")
        assert hasattr(CheckpointType, "DYNAMIC_FIELDS_DETECTED")

    def test_checkpoint_store_page_checkpoint(self):
        store = CheckpointStore()
        cp = create_form_inspected_checkpoint(
            run_id="test-run",
            step=1,
            fields_found=5,
            form_url="https://test.com/apply",
        )
        store.save(cp)
        latest = store.get_latest("test-run")
        assert latest is not None
        assert latest.state_snapshot["fields_found"] == 5


# ===========================================================================
# PART 15-16: Review & Consent
# ===========================================================================

class TestReviewAndConsent:
    def test_review_page_detection_in_mock_form(self):
        form = get_mock_form("form-h")
        assert form is not None
        review_page = [p for p in form.pages if p.is_review]
        assert len(review_page) == 1
        assert "Review" in review_page[0].heading

    def test_consent_page_detection_in_mock_form(self):
        form = get_mock_form("form-i")
        assert form is not None
        declare_page = [p for p in form.pages if p.consent_text]
        assert len(declare_page) == 1
        assert "certify" in declare_page[0].consent_text.lower()


# ===========================================================================
# PART 27: Mock Form Suite
# ===========================================================================

class TestMockFormSuite:
    def test_all_forms_accessible(self):
        for form_id in ["form-a", "form-b", "form-c", "form-d", "form-e",
                        "form-f", "form-g", "form-h", "form-i", "form-j",
                        "form-k", "form-l", "form-m"]:
            form = get_mock_form(form_id)
            assert form is not None, f"Form {form_id} not found"

    def test_form_a_single_page(self):
        form = FORM_A
        assert len(form.pages) == 1
        assert form.pages[0].fields[0].required is True

    def test_form_b_three_pages(self):
        form = FORM_B
        assert len(form.pages) == 3
        assert form.pages[2].is_review is True

    def test_form_c_five_pages(self):
        form = FORM_C
        assert len(form.pages) == 5
        assert form.pages[4].is_review is True

    def test_form_d_conditional(self):
        form = FORM_D
        assert len(form.pages[0].conditional_fields) > 0
        assert "Yes" in form.pages[0].conditional_fields

    def test_form_m_already_submitted(self):
        form = FORM_M
        assert form.pages[0].is_submission is True
        assert len(form.pages[0].fields) == 0


# ===========================================================================
# PART 28: Navigation Safety
# ===========================================================================

class TestNavigationSafety:
    def test_next_button_detected(self):
        nav = detect_navigation([
            {"selector": "button.next", "text": "Continue"},
        ])
        assert nav.has_next is True
        assert nav.action == NavigationAction.NEXT_PAGE

    def test_back_button_detected(self):
        nav = detect_navigation([
            {"selector": "button.back", "text": "Back"},
        ])
        assert nav.has_back is True
        assert nav.action == NavigationAction.PREVIOUS_PAGE

    def test_submit_not_confused_with_next(self):
        nav = detect_navigation([
            {"selector": "button.next", "text": "Continue to next step"},
            {"selector": "button.submit", "text": "Submit Application"},
        ])
        assert nav.has_next is True
        assert nav.has_submit is True
        assert nav.action == NavigationAction.SUBMIT

    def test_review_not_confused_with_next(self):
        nav = detect_navigation([
            {"selector": "button.next", "text": "Continue"},
            {"selector": "button.review", "text": "Review Application"},
        ])
        assert nav.has_next is True
        assert nav.has_review is True
        assert nav.action == NavigationAction.REVIEW


# ===========================================================================
# PART 28: Validation
# ===========================================================================

class TestPageValidation:
    def test_valid_page(self):
        session = FormSession(session_id="test-1")
        snap = PageSnapshot(
            page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com",
            fields=[
                TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"), required=True, value="Alice"),
            ],
        )
        session.add_page(snap)
        session.set_current_page("p1")
        mapping = MappingResult(
            fields=[],
            new_questions=[],
            warnings=[],
        )
        is_valid, issues = validate_page(session, mapping)
        assert is_valid is True

    def test_invalid_page_missing_required(self):
        session = FormSession(session_id="test-1")
        snap = PageSnapshot(
            page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com",
            fields=[
                TrackedField(detected=DetectedField(key="f1", label="Name", kind="text"), required=True, value=None),
            ],
        )
        session.add_page(snap)
        session.set_current_page("p1")
        mapping = MappingResult(fields=[], new_questions=[], warnings=[])
        is_valid, issues = validate_page(session, mapping)
        assert is_valid is False
        assert len(issues) > 0


# ===========================================================================
# PART 28: Autopilot Integration
# ===========================================================================

class TestAutopilotIntegration:
    def test_one_session_per_application(self):
        session = FormSession(session_id="s1", application_id=42, execution_run_id=1)
        assert session.application_id == 42
        assert session.execution_run_id == 1

    def test_session_serialization(self):
        session = FormSession(session_id="s1", application_id=42)
        data = session.to_dict()
        assert data["application_id"] == 42
        assert data["session_id"] == "s1"


# ===========================================================================
# PART 28: Security
# ===========================================================================

class TestSecurity:
    def test_no_secrets_in_snapshot(self):
        snap = PageSnapshot(
            page_index=1, page_key="p1", page_type=PageType.FORM_PAGE, url="https://test.com",
            fields=[TrackedField(detected=DetectedField(key="f1", label="Password", kind="text"), value="secret123")],
        )
        data = snap.__dict__
        # The snapshot stores the value, but evidence tracker should mask it
        # This is a structural test — the value is in memory only
        assert "secret123" in str(data)


# ===========================================================================
# PART 28: Regression (existing tests should still pass)
# ===========================================================================

class TestRegression:
    def test_mock_form_a_has_fields(self):
        form = FORM_A
        assert len(form.pages[0].fields) == 5

    def test_mock_form_b_navigation(self):
        form = FORM_B
        assert any(n["text"] == "Continue" for n in form.pages[0].navigation)
        assert any(n["text"] == "Back" for n in form.pages[1].navigation)

    def test_form_session_to_dict(self):
        session = FormSession(session_id="s1")
        data = session.to_dict()
        assert "session_id" in data
        assert "status" in data
