"""Phase 16: Advanced form controls + file handling tests.

Tests cover:
- Field detection for advanced control types
- Value normalization (date, currency, multi-select, checkbox, radio, autocomplete)
- File validation and safe file handling
- Mock driver integration with advanced scenarios
- Evidence recording for advanced fields
- Safety tests (no arbitrary file access, no unverified uploads)
"""
from __future__ import annotations

import os
import tempfile

from app.application_execution.base import (
    FIELD_KINDS,
    DetectedField,
)
from app.application_execution.evidence_tracker import (
    EvidenceRecord,
    EvidenceStore,
    EVIDENCE_FILE_UPLOADED,
    EVIDENCE_FILE_UPLOAD_FAILED,
    EVIDENCE_CHECKBOX_TOGGLED,
    EVIDENCE_RADIO_SELECTED,
    EVIDENCE_MULTI_SELECT_CHANGED,
    EVIDENCE_AUTOCOMPLETE_SELECTED,
    EVIDENCE_DATE_FILLED,
    EVIDENCE_CURRENCY_FILLED,
    record_advanced_field_fill,
    record_file_upload,
    record_file_validation,
)
from app.application_execution.field_catalog import (
    ADVANCED_CONTROL_FIELDS,
    ALL_FIELD_CONCEPTS,
    lookup_concept,
)
from app.application_execution.file_handler import (
    DOCUMENT_TYPES,
    FILE_VALIDATION_STATUSES,
    detect_document_type_from_label,
    get_file_size,
    validate_file_extension,
    validate_file_exists,
    validate_file_for_upload,
    validate_file_mime_type,
    validate_file_ownership,
    validate_file_size,
)
from app.application_execution.human_approval import ApprovalAction
from app.application_execution.normalizer import (
    detect_date_format,
    format_currency_for_display,
    normalize_autocomplete_input,
    normalize_checkbox_value,
    normalize_currency,
    normalize_date,
    normalize_multi_select,
    normalize_radio_value,
    select_autocomplete_suggestion,
)


# ---------------------------------------------------------------------------
# Step 2: FIELD_KINDS includes advanced types
# ---------------------------------------------------------------------------


class TestFieldKindsExtended:
    """Verify FIELD_KINDS includes all advanced control types."""

    def test_checkbox_kind_exists(self):
        assert "checkbox" in FIELD_KINDS

    def test_multi_select_kind_exists(self):
        assert "multi_select" in FIELD_KINDS

    def test_currency_kind_exists(self):
        assert "currency" in FIELD_KINDS

    def test_autocomplete_kind_exists(self):
        assert "autocomplete" in FIELD_KINDS

    def test_all_expected_kinds(self):
        expected = {
            "text", "textarea", "select", "radio", "checkbox",
            "file", "date", "multi_select", "currency", "autocomplete",
        }
        assert set(FIELD_KINDS) == expected


class TestDetectedFieldAdvanced:
    """Verify DetectedField supports advanced metadata."""

    def test_checkbox_field(self):
        f = DetectedField(key="cb1", label="I agree", kind="checkbox", required=True)
        assert f.kind == "checkbox"
        assert f.required is True

    def test_multi_select_field(self):
        f = DetectedField(
            key="ms1", label="Skills", kind="multi_select",
            options=["Python", "JS"], multiple=True,
        )
        assert f.kind == "multi_select"
        assert f.multiple is True
        assert len(f.options) == 2

    def test_currency_field(self):
        f = DetectedField(key="cu1", label="Salary", kind="currency", min_value=0)
        assert f.kind == "currency"
        assert f.min_value == 0

    def test_autocomplete_field(self):
        f = DetectedField(key="ac1", label="City", kind="autocomplete")
        assert f.kind == "autocomplete"

    def test_file_field_with_accepted_types(self):
        f = DetectedField(
            key="fr1", label="Upload Resume", kind="file",
            accepted_types=["resume"],
        )
        assert f.accepted_types == ["resume"]


# ---------------------------------------------------------------------------
# Step 3: Value normalization
# ---------------------------------------------------------------------------


class TestDateNormalization:
    """Test date normalization across formats."""

    def test_iso_format(self):
        assert normalize_date("2026-09-15") == "2026-09-15"

    def test_dd_mm_yyyy(self):
        assert normalize_date("15/09/2026") == "2026-09-15"

    def test_mm_dd_yyyy(self):
        assert normalize_date("09/15/2026") == "2026-09-15"

    def test_month_name(self):
        assert normalize_date("September 15, 2026") == "2026-09-15"

    def test_dash_separated(self):
        assert normalize_date("15-09-2026") == "2026-09-15"

    def test_custom_target_format(self):
        assert normalize_date("2026-09-15", "%d/%m/%Y") == "15/09/2026"

    def test_empty_input(self):
        assert normalize_date("") is None
        assert normalize_date("   ") is None

    def test_invalid_date(self):
        assert normalize_date("not a date") is None

    def test_detect_format_iso(self):
        assert detect_date_format("2026-09-15") == "YYYY-MM-DD"

    def test_detect_format_dd_mm(self):
        assert detect_date_format("15/09/2026") == "DD/MM/YYYY"

    def test_detect_format_unknown(self):
        assert detect_date_format("hello") is None


class TestCurrencyNormalization:
    """Test currency normalization."""

    def test_plain_number(self):
        amount, code = normalize_currency("100000")
        assert amount == 100000.0
        assert code is None

    def test_dollar_sign(self):
        amount, code = normalize_currency("$80,000")
        assert amount == 80000.0
        assert code == "USD"

    def test_rupee_sign(self):
        amount, code = normalize_currency("₹12,00,000")
        assert amount == 1200000.0
        assert code == "INR"

    def test_lpa_suffix(self):
        amount, code = normalize_currency("15 LPA")
        assert amount == 15.0

    def test_euro_sign(self):
        amount, code = normalize_currency("€50,000")
        assert amount == 50000.0
        assert code == "EUR"

    def test_decimal(self):
        amount, code = normalize_currency("$80,500.50")
        assert amount == 80500.50

    def test_empty(self):
        amount, code = normalize_currency("")
        assert amount is None
        assert code is None

    def test_format_display(self):
        assert format_currency_for_display(80000) == "80,000"
        assert format_currency_for_display(80500.50) == "80,500.50"


class TestMultiSelectNormalization:
    """Test multi-select value normalization."""

    def test_exact_match(self):
        matched, unmatched = normalize_multi_select(
            ["Python", "JavaScript"],
            ["Python", "JavaScript", "React", "Node.js"],
        )
        assert matched == ["Python", "JavaScript"]
        assert unmatched == []

    def test_case_insensitive(self):
        matched, unmatched = normalize_multi_select(
            ["python", "JAVASCRIPT"],
            ["Python", "JavaScript"],
        )
        assert matched == ["Python", "JavaScript"]
        assert unmatched == []

    def test_partial_match(self):
        matched, unmatched = normalize_multi_select(
            ["Java Script"],
            ["JavaScript", "Python"],
        )
        assert matched == []  # normalizer does exact token match, not fuzzy

    def test_no_match(self):
        matched, unmatched = normalize_multi_select(
            ["Fortran", "COBOL"],
            ["Python", "JavaScript"],
        )
        assert matched == []
        assert unmatched == ["Fortran", "COBOL"]

    def test_empty_requests(self):
        matched, unmatched = normalize_multi_select([], ["Python"])
        assert matched == []
        assert unmatched == []


class TestCheckboxNormalization:
    """Test checkbox value normalization."""

    def test_true_values(self):
        for v in ("true", "yes", "1", "on", "checked", "selected"):
            assert normalize_checkbox_value(v) is True

    def test_false_values(self):
        for v in ("false", "no", "0", "off", "unchecked", ""):
            assert normalize_checkbox_value(v) is False

    def test_none(self):
        assert normalize_checkbox_value(None) is None

    def test_unknown(self):
        assert normalize_checkbox_value("maybe") is None


class TestRadioNormalization:
    """Test radio value normalization."""

    def test_exact_match(self):
        result = normalize_radio_value("Full-time", ["Full-time", "Part-time"])
        assert result == "Full-time"

    def test_case_insensitive(self):
        result = normalize_radio_value("full-time", ["Full-time", "Part-time"])
        assert result == "Full-time"

    def test_no_match(self):
        result = normalize_radio_value("Freelance", ["Full-time", "Part-time"])
        assert result is None

    def test_empty_options(self):
        result = normalize_radio_value("Full-time", [])
        assert result is None


class TestAutocompleteNormalization:
    """Test autocomplete input normalization and suggestion selection."""

    def test_clean_input(self):
        assert normalize_autocomplete_input("  San Francisco,  ") == "San Francisco"

    def test_trailing_comma(self):
        assert normalize_autocomplete_input("New York,") == "New York"

    def test_exact_suggestion(self):
        result = select_autocomplete_suggestion(
            "San Francisco",
            ["San Francisco", "New York", "Seattle"],
        )
        assert result == "San Francisco"

    def test_prefix_suggestion(self):
        result = select_autocomplete_suggestion(
            "San",
            ["San Francisco", "New York", "Seattle"],
        )
        assert result == "San Francisco"

    def test_ambiguous_suggestions(self):
        result = select_autocomplete_suggestion(
            "San",
            ["San Francisco", "San Diego", "San Jose"],
        )
        assert result is None  # ambiguous

    def test_no_match(self):
        result = select_autocomplete_suggestion(
            "London",
            ["San Francisco", "New York"],
        )
        assert result is None

    def test_empty_suggestions(self):
        result = select_autocomplete_suggestion("test", [])
        assert result is None


# ---------------------------------------------------------------------------
# Step 4/6: File handling and validation
# ---------------------------------------------------------------------------


class TestFileValidation:
    """Test file validation chain."""

    def test_valid_file_exists(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"test content")
            path = f.name
        try:
            result = validate_file_exists(path)
            assert result.status == "VALID"
        finally:
            os.unlink(path)

    def test_missing_file(self):
        result = validate_file_exists("/nonexistent/file.pdf")
        assert result.status == "MISSING"

    def test_empty_path(self):
        result = validate_file_exists("")
        assert result.status == "MISSING"

    def test_valid_extension(self):
        result = validate_file_extension("resume.pdf", "resume")
        assert result.status == "VALID"

    def test_invalid_extension(self):
        result = validate_file_extension("script.exe", "resume")
        assert result.status == "INVALID_EXTENSION"

    def test_valid_mime(self):
        result = validate_file_mime_type("application/pdf", "resume")
        assert result.status == "VALID"

    def test_invalid_mime(self):
        result = validate_file_mime_type("application/exe", "resume")
        assert result.status == "INVALID_MIME"

    def test_valid_size(self):
        result = validate_file_size(1024)
        assert result.status == "VALID"

    def test_too_large(self):
        result = validate_file_size(20 * 1024 * 1024)  # 20 MB
        assert result.status == "TOO_LARGE"

    def test_empty_file(self):
        result = validate_file_size(0)
        assert result.status == "MISSING"

    def test_ownership_valid(self):
        result = validate_file_ownership("resume.pdf", 1, 1)
        assert result.status == "VALID"

    def test_ownership_mismatch(self):
        result = validate_file_ownership("resume.pdf", 2, 1)
        assert result.status == "NOT_VERIFIED"

    def test_ownership_no_expected(self):
        result = validate_file_ownership("resume.pdf", 1, None)
        assert result.status == "VALID"

    def test_full_validation_valid(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"test content")
            path = f.name
        try:
            result = validate_file_for_upload(
                file_path=path,
                content_type="application/pdf",
                document_type="resume",
                size_bytes=12,
            )
            assert result.status == "VALID"
        finally:
            os.unlink(path)

    def test_full_validation_missing(self):
        result = validate_file_for_upload(
            file_path="/nonexistent.pdf",
            content_type="application/pdf",
            document_type="resume",
        )
        assert result.status == "MISSING"

    def test_document_type_detection_resume(self):
        assert detect_document_type_from_label("Upload Resume") == "resume"
        assert detect_document_type_from_label("CV") == "resume"

    def test_document_type_detection_cover_letter(self):
        assert detect_document_type_from_label("Cover Letter") == "cover_letter"

    def test_document_type_detection_portfolio(self):
        assert detect_document_type_from_label("Portfolio") == "portfolio"

    def test_document_type_detection_certificate(self):
        assert detect_document_type_from_label("Certificate") == "certificate"

    def test_document_type_detection_unknown(self):
        assert detect_document_type_from_label("Other Field") is None

    def test_file_size_retrieval(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello")
            path = f.name
        try:
            assert get_file_size(path) == 5
        finally:
            os.unlink(path)

    def test_file_size_nonexistent(self):
        assert get_file_size("/nonexistent") is None

    def test_all_document_types_covered(self):
        assert set(DOCUMENT_TYPES) >= {"resume", "cover_letter", "portfolio", "certificate", "other"}

    def test_all_validation_statuses(self):
        assert "VALID" in FILE_VALIDATION_STATUSES
        assert "MISSING" in FILE_VALIDATION_STATUSES
        assert "INVALID_EXTENSION" in FILE_VALIDATION_STATUSES
        assert "UPLOAD_FAILED" in FILE_VALIDATION_STATUSES
        assert "UPLOAD_VERIFIED" in FILE_VALIDATION_STATUSES


# ---------------------------------------------------------------------------
# Step 5: Field catalog advanced fields
# ---------------------------------------------------------------------------


class TestFieldCatalogAdvanced:
    """Verify field catalog includes advanced field concepts."""

    def test_terms_acceptance_exists(self):
        concept = lookup_concept("I agree to the Terms")
        assert concept is not None
        assert concept.canonical == "TERMS_ACCEPTANCE"

    def test_employment_type_exists(self):
        concept = lookup_concept("Employment Type")
        assert concept is not None
        assert concept.canonical == "EMPLOYMENT_TYPE"

    def test_skills_multi_exists(self):
        concept = lookup_concept("Preferred Technologies")
        assert concept is not None
        assert concept.canonical == "SKILLS_MULTI"

    def test_availability_date_exists(self):
        concept = lookup_concept("Availability Date")
        assert concept is not None
        assert concept.canonical == "AVAILABILITY_DATE"

    def test_expected_salary_exists(self):
        concept = lookup_concept("Expected Salary")
        assert concept is not None
        assert concept.canonical == "SALARY_EXPECTATION"

    def test_city_location_exists(self):
        concept = lookup_concept("City")
        assert concept is not None
        assert concept.canonical == "LOCATION"

    def test_certificate_file_exists(self):
        concept = lookup_concept("Certificate")
        assert concept is not None
        assert concept.canonical == "CERTIFICATE_FILE"

    def test_advanced_fields_in_catalog(self):
        advanced_canonicals = {f.canonical for f in ADVANCED_CONTROL_FIELDS}
        assert "TERMS_ACCEPTANCE" in advanced_canonicals
        assert "EMPLOYMENT_TYPE" in advanced_canonicals
        assert "SKILLS_MULTI" in advanced_canonicals
        assert "AVAILABILITY_DATE" in advanced_canonicals
        assert "EXPECTED_SALARY" in advanced_canonicals
        assert "CITY_LOCATION" in advanced_canonicals

    def test_all_advanced_in_all_fields(self):
        all_canonicals = {f.canonical for f in ALL_FIELD_CONCEPTS}
        for f in ADVANCED_CONTROL_FIELDS:
            assert f.canonical in all_canonicals


# ---------------------------------------------------------------------------
# Step 8: Evidence tracking for advanced fields
# ---------------------------------------------------------------------------


class TestEvidenceAdvancedFields:
    """Test evidence recording for advanced control types."""

    def setup_method(self):
        self.store = EvidenceStore()

    def test_record_checkbox_evidence(self):
        record = record_advanced_field_fill(
            self.store, "run-1", 1, "I agree", "TERMS_ACCEPTANCE",
            "checkbox", "true",
        )
        assert record.evidence_type == EVIDENCE_CHECKBOX_TOGGLED
        assert record.control_type == "checkbox"
        assert record.after_value == "true"

    def test_record_radio_evidence(self):
        record = record_advanced_field_fill(
            self.store, "run-1", 1, "Employment Type", "EMPLOYMENT_TYPE",
            "radio", "Full-time",
        )
        assert record.evidence_type == EVIDENCE_RADIO_SELECTED
        assert record.control_type == "radio"

    def test_record_multi_select_evidence(self):
        record = record_advanced_field_fill(
            self.store, "run-1", 1, "Skills", "SKILLS_MULTI",
            "multi_select", "Python, JavaScript",
        )
        assert record.evidence_type == EVIDENCE_MULTI_SELECT_CHANGED
        assert record.control_type == "multi_select"

    def test_record_autocomplete_evidence(self):
        record = record_advanced_field_fill(
            self.store, "run-1", 1, "City", "CITY_LOCATION",
            "autocomplete", "San Francisco",
        )
        assert record.evidence_type == EVIDENCE_AUTOCOMPLETE_SELECTED
        assert record.control_type == "autocomplete"

    def test_record_date_evidence(self):
        record = record_advanced_field_fill(
            self.store, "run-1", 1, "Start Date", "AVAILABILITY_DATE",
            "date", "2026-10-01",
        )
        assert record.evidence_type == EVIDENCE_DATE_FILLED
        assert record.control_type == "date"

    def test_record_currency_evidence(self):
        record = record_advanced_field_fill(
            self.store, "run-1", 1, "Salary", "EXPECTED_SALARY",
            "currency", "80000",
        )
        assert record.evidence_type == EVIDENCE_CURRENCY_FILLED
        assert record.control_type == "currency"

    def test_record_file_upload_success(self):
        record = record_file_upload(
            self.store, "run-1", 1, "Upload Resume", "resume",
            "resume.pdf", "application/pdf", True,
        )
        assert record.evidence_type == EVIDENCE_FILE_UPLOADED
        assert record.document_type == "resume"
        assert record.uploaded_filename == "resume.pdf"
        assert record.success is True

    def test_record_file_upload_failure(self):
        record = record_file_upload(
            self.store, "run-1", 1, "Upload Resume", "resume",
            "script.exe", "application/exe", False,
            validation_result="INVALID_EXTENSION",
            error_message="Invalid file type",
        )
        assert record.evidence_type == EVIDENCE_FILE_UPLOAD_FAILED
        assert record.success is False
        assert record.validation_result == "INVALID_EXTENSION"

    def test_record_file_validation_success(self):
        record = record_file_validation(
            self.store, "run-1", 1, "Upload Resume", "resume",
            "resume.pdf", "VALID",
        )
        assert record.evidence_type == "FILE_VALIDATED"
        assert record.validation_result == "VALID"

    def test_record_file_validation_failure(self):
        record = record_file_validation(
            self.store, "run-1", 1, "Upload Resume", "resume",
            "script.exe", "INVALID_EXTENSION",
        )
        assert record.evidence_type == "FILE_VALIDATION_FAILED"
        assert record.success is False


# ---------------------------------------------------------------------------
# Step 9: Mock driver advanced scenarios
# ---------------------------------------------------------------------------


class TestMockBrowserDriverAdvanced:
    """Test MockBrowserDriver with advanced field scenarios."""

    def _driver(self, scenario: str):
        from app.application_execution.browser import MockBrowserDriver
        return MockBrowserDriver(f"mock://{scenario}")

    def test_checkbox_scenario(self):
        driver = self._driver("advanced-checkbox")
        driver.open(driver.url)
        fields = driver.inspect_form()
        assert any(f.kind == "checkbox" for f in fields)
        checkbox_fields = [f for f in fields if f.kind == "checkbox"]
        assert len(checkbox_fields) == 3

    def test_radio_scenario(self):
        driver = self._driver("advanced-radio")
        driver.open(driver.url)
        fields = driver.inspect_form()
        radio_fields = [f for f in fields if f.kind == "radio"]
        assert len(radio_fields) == 3
        assert radio_fields[0].options == ["Full-time", "Part-time", "Contract", "Internship"]

    def test_multi_select_scenario(self):
        driver = self._driver("advanced-multi-select")
        driver.open(driver.url)
        fields = driver.inspect_form()
        ms_fields = [f for f in fields if f.kind == "multi_select"]
        assert len(ms_fields) == 2
        assert ms_fields[0].multiple is True

    def test_date_scenario(self):
        driver = self._driver("advanced-date")
        driver.open(driver.url)
        fields = driver.inspect_form()
        date_fields = [f for f in fields if f.kind == "date"]
        assert len(date_fields) == 3

    def test_currency_scenario(self):
        driver = self._driver("advanced-currency")
        driver.open(driver.url)
        fields = driver.inspect_form()
        currency_fields = [f for f in fields if f.kind == "currency"]
        assert len(currency_fields) == 2

    def test_autocomplete_scenario(self):
        driver = self._driver("advanced-autocomplete")
        driver.open(driver.url)
        fields = driver.inspect_form()
        ac_fields = [f for f in fields if f.kind == "autocomplete"]
        assert len(ac_fields) == 3

    def test_file_upload_required(self):
        driver = self._driver("advanced-file-required")
        driver.open(driver.url)
        fields = driver.inspect_form()
        file_fields = [f for f in fields if f.kind == "file"]
        assert len(file_fields) == 1
        assert file_fields[0].required is True

    def test_file_upload_optional(self):
        driver = self._driver("advanced-file-optional")
        driver.open(driver.url)
        fields = driver.inspect_form()
        file_fields = [f for f in fields if f.kind == "file"]
        assert len(file_fields) == 2
        assert file_fields[0].required is True
        assert file_fields[1].required is False

    def test_file_upload_multiple(self):
        driver = self._driver("advanced-file-multiple")
        driver.open(driver.url)
        fields = driver.inspect_form()
        file_fields = [f for f in fields if f.kind == "file"]
        assert len(file_fields) == 3

    def test_fill_checkbox(self):
        driver = self._driver("advanced-checkbox")
        driver.open(driver.url)
        result = driver.fill("cb1", "true")
        assert result.status == "KNOWN"
        assert result.value == "true"

    def test_fill_radio(self):
        driver = self._driver("advanced-radio")
        driver.open(driver.url)
        result = driver.fill("r1", "Full-time")
        assert result.status == "KNOWN"

    def test_fill_date(self):
        driver = self._driver("advanced-date")
        driver.open(driver.url)
        result = driver.fill("dt1", "2026-10-01")
        assert result.status == "KNOWN"

    def test_fill_currency(self):
        driver = self._driver("advanced-currency")
        driver.open(driver.url)
        result = driver.fill("cu1", "80000")
        assert result.status == "KNOWN"

    def test_fill_autocomplete(self):
        driver = self._driver("advanced-autocomplete")
        driver.open(driver.url)
        result = driver.fill("ac1", "San Francisco")
        assert result.status == "KNOWN"

    def test_upload_file_valid(self):
        driver = self._driver("advanced-file-required")
        driver.open(driver.url)
        result = driver.upload_file(b"resume content", "resume.pdf", "application/pdf", "resume")
        assert result.status == "KNOWN"
        assert result.control_type == "file"
        assert driver.uploaded == ("resume.pdf", "application/pdf")

    def test_upload_file_invalid_ext(self):
        driver = self._driver("advanced-file-invalid")
        driver.open(driver.url)
        result = driver.upload_file(b"content", "script.exe", "application/exe", "resume")
        assert result.status == "REQUIRES_REVIEW"

    def test_upload_file_empty(self):
        driver = self._driver("advanced-file-required")
        driver.open(driver.url)
        result = driver.upload_file(b"", "resume.pdf", "application/pdf", "resume")
        assert result.status == "UNKNOWN"

    def test_autocomplete_suggestions(self):
        driver = self._driver("advanced-autocomplete")
        driver.open(driver.url)
        suggestions = driver.get_autocomplete_suggestions("ac1", "San")
        assert "San Francisco" in suggestions

    def test_autocomplete_no_match(self):
        driver = self._driver("advanced-autocomplete")
        driver.open(driver.url)
        suggestions = driver.get_autocomplete_suggestions("ac1", "London")
        assert suggestions == []

    def test_mixed_scenario(self):
        driver = self._driver("advanced-mixed")
        driver.open(driver.url)
        fields = driver.inspect_form()
        kinds = {f.kind for f in fields}
        assert "checkbox" in kinds
        assert "radio" in kinds
        assert "multi_select" in kinds
        assert "date" in kinds
        assert "currency" in kinds
        assert "autocomplete" in kinds
        assert "file" in kinds

    def test_file_field_accepted_types(self):
        driver = self._driver("advanced-file-required")
        fields = driver.inspect_form()
        file_fields = [f for f in fields if f.kind == "file"]
        assert file_fields[0].accepted_types == ["resume"]

    def test_file_field_ambiguous_accepted_types(self):
        driver = self._driver("advanced-file-ambiguous")
        fields = driver.inspect_form()
        file_fields = [f for f in fields if f.kind == "file"]
        assert file_fields[0].accepted_types == ["resume", "cover_letter", "certificate"]


# ---------------------------------------------------------------------------
# Step 11: Safety tests
# ---------------------------------------------------------------------------


class TestSafetyInvariants:
    """Verify safety invariants are maintained."""

    def test_no_arbitrary_file_upload(self):
        """Arbitrary local files cannot be uploaded via the mock driver."""
        driver_driver = None
        try:
            from app.application_execution.browser import MockBrowserDriver
            driver_driver = MockBrowserDriver("mock://advanced-file-required")
            driver_driver.open(driver_driver.url)
            # Try to upload a file that is not in the approved list
            result = driver_driver.upload_file(
                b"content", "malicious.exe", "application/x-executable", "resume",
            )
            # Should be rejected
            assert result.status == "REQUIRES_REVIEW"
        finally:
            pass

    def test_file_validation_blocks_invalid(self):
        """Invalid file extensions are blocked by validation."""
        result = validate_file_extension("script.exe", "resume")
        assert result.status == "INVALID_EXTENSION"

    def test_file_validation_blocks_oversized(self):
        """Oversized files are blocked by validation."""
        result = validate_file_size(100 * 1024 * 1024)  # 100 MB
        assert result.status == "TOO_LARGE"

    def test_ownership_enforced(self):
        """Files from wrong package are rejected."""
        result = validate_file_ownership("resume.pdf", package_id=2, expected_package_id=1)
        assert result.status == "NOT_VERIFIED"

    def test_no_empty_file_upload(self):
        """Empty files are rejected."""
        result = validate_file_size(0)
        assert result.status == "MISSING"

    def test_human_approval_actions_include_upload(self):
        """File upload is listed as an approval action."""
        assert ApprovalAction.UPLOAD_FILE.value == "UPLOAD_FILE"
        assert ApprovalAction.AMBIGUOUS_DOCUMENT_SELECTION.value == "AMBIGUOUS_DOCUMENT_SELECTION"

    def test_no_document_contents_in_evidence(self):
        """Evidence records never contain file contents."""
        store = EvidenceStore()
        record = record_file_upload(
            store, "run-1", 1, "Upload Resume", "resume",
            "resume.pdf", "application/pdf", True,
        )
        # Evidence should contain filename but NOT file contents
        assert record.uploaded_filename == "resume.pdf"
        assert "resume content" not in str(record.metadata)
        assert "b'" not in str(record.metadata)

    def test_no_credential_in_evidence(self):
        """Evidence records never contain credentials."""
        record = EvidenceRecord(
            run_id="test",
            evidence_type="TEST",
            field_label="password",
            after_value="***",
        )
        assert "password" not in str(record.data_hash)


# ---------------------------------------------------------------------------
# Regression: existing single-page execution still works
# ---------------------------------------------------------------------------


class TestRegressionBasicExecution:
    """Verify basic form execution still works."""

    def test_simple_form_inspection(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://simple-form")
        driver.open(driver.url)
        fields = driver.inspect_form()
        assert len(fields) >= 5
        assert any(f.label == "First Name" for f in fields)

    def test_simple_form_fill(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://simple-form")
        driver.open(driver.url)
        result = driver.fill("f1", "John")
        assert result.status == "KNOWN"
        assert result.value == "John"

    def test_resume_upload_original(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://resume-upload")
        driver.open(driver.url)
        result = driver.upload_resume(b"resume content", "resume.pdf", "application/pdf")
        assert result.status == "KNOWN"

    def test_submission_success(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://confirmation")
        driver.open(driver.url)
        result = driver.submit()
        assert result.confirmed is True

    def test_submission_failure(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://failed-submit")
        driver.open(driver.url)
        result = driver.submit()
        assert result.failure is True

    def test_captcha_detection(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://captcha")
        driver.open(driver.url)
        assert driver.detect_captcha() is True

    def test_login_detection(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://login-required")
        driver.open(driver.url)
        assert driver.detect_login() is True
