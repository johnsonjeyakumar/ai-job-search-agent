"""Phase 17: End-to-end advanced form execution integration tests.

Tests the REAL execution pipeline (executor.py + form_orchestrator.py)
with advanced controls, file uploads, normalization, evidence, and approval.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application_execution import base
from app.application_execution.base import (
    DetectedField,
    KNOWN,
    REQUIRES_REVIEW,
    UNKNOWN,
)
from app.application_execution.evidence_tracker import EvidenceStore
from app.application_execution.fields import (
    MappedField,
    ProfileContext,
    map_fields,
)
from app.application_execution.form_orchestrator import (
    maybe_request_file_approval,
    normalize_field_value,
    record_fill_evidence,
    record_file_evidence,
    resolve_file_for_upload,
    validate_and_upload_file,
)
from app.application_execution.human_approval import ApprovalStore, ApprovalAction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Use the test database from conftest.py."""
    from app.config.settings import get_settings
    import app.models  # noqa: F401
    settings = get_settings()
    url = str(settings.database_url).replace(settings.database_url.split("/")[-1], "job_agent_test")
    engine = create_engine(url)
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture()
def profile_ctx():
    return ProfileContext(
        full_name="John Smith",
        email="john@example.com",
        phone="+1-555-0123",
        city="San Francisco",
        state="CA",
        country="USA",
        linkedin_url="https://linkedin.com/in/john",
        degree="BS Computer Science",
        university="MIT",
        graduation_year=2020,
        experience_level="3-5 years",
        notice_period="30 days",
        work_authorization="Authorized",
        salary_preference="$80,000-$100,000",
        remote_preference="Remote",
        employment_types=["Full-time"],
        skills=["Python", "JavaScript", "React", "SQL", "AWS"],
    )


@pytest.fixture()
def evidence_store():
    return EvidenceStore()


@pytest.fixture()
def approval_store():
    return ApprovalStore()


# ---------------------------------------------------------------------------
# Part 1: Normalization integration
# ---------------------------------------------------------------------------

class TestFieldNormalization:
    """Test normalization of values through the orchestrator."""

    def test_date_normalization(self, profile_ctx):
        raw = DetectedField(key="dt1", label="Availability Date", kind="date")
        mapped = MappedField(
            detected=raw, matched_key="availability_date",
            value="15/09/2026", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "2026-09-15"
        assert error is None

    def test_currency_normalization(self, profile_ctx):
        raw = DetectedField(key="cu1", label="Expected Salary", kind="currency")
        mapped = MappedField(
            detected=raw, matched_key="expected_salary",
            value="$80,000", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "80000.0"
        assert error is None

    def test_checkbox_normalization(self, profile_ctx):
        raw = DetectedField(key="cb1", label="Terms", kind="checkbox")
        mapped = MappedField(
            detected=raw, matched_key="terms_acceptance",
            value="yes", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "true"
        assert error is None

    def test_radio_normalization(self, profile_ctx):
        raw = DetectedField(
            key="r1", label="Employment Type", kind="radio",
            options=["Full-time", "Part-time", "Contract"],
        )
        mapped = MappedField(
            detected=raw, matched_key="employment_type",
            value="full-time", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "Full-time"
        assert error is None

    def test_multi_select_normalization(self, profile_ctx):
        raw = DetectedField(
            key="ms1", label="Skills", kind="multi_select",
            options=["Python", "JavaScript", "React", "SQL"],
            multiple=True,
        )
        mapped = MappedField(
            detected=raw, matched_key="skills",
            value="Python, JavaScript", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "Python, JavaScript"
        assert error is None

    def test_multi_select_unmatched_options(self, profile_ctx):
        raw = DetectedField(
            key="ms1", label="Skills", kind="multi_select",
            options=["Python", "JavaScript"],
            multiple=True,
        )
        mapped = MappedField(
            detected=raw, matched_key="skills",
            value="Python, Fortran", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized is None
        assert "Fortran" in (error or "")

    def test_autocomplete_normalization(self, profile_ctx):
        raw = DetectedField(key="ac1", label="City", kind="autocomplete")
        mapped = MappedField(
            detected=raw, matched_key="city_location",
            value="  San Francisco,  ", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "San Francisco"
        assert error is None

    def test_text_passthrough(self, profile_ctx):
        raw = DetectedField(key="f1", label="First Name", kind="text")
        mapped = MappedField(
            detected=raw, matched_key="first_name",
            value="John", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "John"
        assert error is None

    def test_select_with_options(self, profile_ctx):
        raw = DetectedField(
            key="s1", label="Experience", kind="select",
            options=["0-2 years", "3-5 years", "5+ years"],
        )
        mapped = MappedField(
            detected=raw, matched_key="experience_level",
            value="3-5 years", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "3-5 years"
        assert error is None

    def test_unknown_kind_passthrough(self, profile_ctx):
        raw = DetectedField(key="x1", label="Custom", kind="custom_type")
        mapped = MappedField(
            detected=raw, matched_key="custom",
            value="test", classification=KNOWN,
        )
        normalized, error = normalize_field_value(mapped, raw)
        assert normalized == "test"
        assert error is None


# ---------------------------------------------------------------------------
# Part 2: Field mapping with advanced fields
# ---------------------------------------------------------------------------

class TestAdvancedFieldMapping:
    """Test mapping of advanced fields through the real mapper."""

    def test_checkbox_mapped_as_known(self, profile_ctx):
        raw = DetectedField(key="cb1", label="I agree to the Terms", kind="checkbox", required=True)
        result = map_fields([raw], profile_ctx)
        assert len(result.fields) == 1
        f = result.fields[0]
        assert f.detected.kind == "checkbox"
        # terms_acceptance provider returns None (never auto-accept)
        assert f.classification == REQUIRES_REVIEW

    def test_radio_employment_type(self, profile_ctx):
        raw = DetectedField(
            key="r1", label="Employment Type", kind="radio",
            options=["Full-time", "Part-time", "Contract"],
        )
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.matched_key == "employment_type"
        assert f.value == "Full-time"
        assert f.classification == KNOWN

    def test_multi_select_skills(self, profile_ctx):
        raw = DetectedField(
            key="ms1", label="Preferred Technologies", kind="multi_select",
            options=["Python", "JavaScript", "React", "Node.js"],
            multiple=True,
        )
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.matched_key == "skills_multi"
        assert "Python" in (f.value or "")
        assert f.classification == KNOWN

    def test_date_availability(self, profile_ctx):
        raw = DetectedField(key="dt1", label="Availability Date", kind="date")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.matched_key == "availability_date"
        # No stored value for availability_date
        assert f.classification == REQUIRES_REVIEW

    def test_currency_expected_salary(self, profile_ctx):
        raw = DetectedField(key="cu1", label="Expected Salary", kind="currency")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        # "Expected Salary" matches existing "salary_preference" spec
        assert f.matched_key == "salary_preference"
        assert f.value == "$80,000-$100,000"
        assert f.classification == KNOWN

    def test_currency_desired_compensation(self, profile_ctx):
        raw = DetectedField(key="cu1", label="Desired Compensation", kind="currency")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        # "Desired Compensation" matches new "expected_salary" spec
        assert f.matched_key == "expected_salary"
        assert f.value == "$80,000-$100,000"
        assert f.classification == KNOWN

    def test_autocomplete_city(self, profile_ctx):
        raw = DetectedField(key="ac1", label="City", kind="autocomplete")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        # "City" matches existing "city" FieldSpec, not the new "city_location"
        assert f.matched_key == "city"
        assert f.value == "San Francisco"
        assert f.classification == KNOWN

    def test_autocomplete_city_location(self, profile_ctx):
        raw = DetectedField(key="ac1", label="City/Location", kind="autocomplete")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.matched_key == "city_location"
        assert f.value == "San Francisco"
        assert f.classification == KNOWN

    def test_file_resume(self, profile_ctx):
        raw = DetectedField(key="fr1", label="Upload Resume", kind="file", required=True)
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.detected.kind == "file"
        assert f.classification == REQUIRES_REVIEW

    def test_file_unknown_type(self, profile_ctx):
        raw = DetectedField(key="fx1", label="Upload Portfolio", kind="file")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.classification == UNKNOWN


# ---------------------------------------------------------------------------
# Part 3: File handling integration
# ---------------------------------------------------------------------------

class TestFileHandlingIntegration:
    """Test file resolution and validation through the orchestrator."""

    def test_resolve_resume_file(self):
        class FakeResume:
            file_path = "/tmp/test.pdf"
            file_name = "resume.pdf"
            content_type = "application/pdf"

        field = DetectedField(key="fr1", label="Upload Resume", kind="file")
        data, fn, ct, dt, err = resolve_file_for_upload(field, resume=FakeResume())
        # Will fail to load from storage, but should return error
        assert err is not None
        assert dt == "resume"

    def test_resolve_non_resume_file(self):
        field = DetectedField(key="fx1", label="Upload Cover Letter", kind="file")
        data, fn, ct, dt, err = resolve_file_for_upload(field)
        assert data is None
        assert dt == "cover_letter"
        assert err is None

    def test_validate_file_upload_invalid_ext(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://advanced-file-invalid")
        driver.open(driver.url)
        result, err = validate_and_upload_file(
            driver, b"content", "script.exe", "application/exe", "resume",
        )
        assert result.status == "REQUIRES_REVIEW"

    def test_validate_file_upload_empty_data(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://advanced-file-required")
        driver.open(driver.url)
        result, err = validate_and_upload_file(
            driver, b"", "resume.pdf", "application/pdf", "resume",
        )
        # Empty data should fail validation
        assert result.status == "REQUIRES_REVIEW" or err is not None


# ---------------------------------------------------------------------------
# Part 4: Approval integration
# ---------------------------------------------------------------------------

class TestApprovalIntegration:
    """Test approval requests for file uploads and ambiguous documents."""

    def test_ambiguous_document_approval(self, approval_store):
        action = maybe_request_file_approval(
            approval_store, "run-1", "Supporting Documents", "other",
            is_ambiguous=True,
            accepted_types=["resume", "cover_letter", "certificate"],
        )
        assert action == ApprovalAction.AMBIGUOUS_DOCUMENT_SELECTION.value
        pending = approval_store.get_pending("run-1")
        assert len(pending) == 1
        assert pending[0].action == ApprovalAction.AMBIGUOUS_DOCUMENT_SELECTION.value

    def test_resume_upload_no_approval_needed(self, approval_store):
        action = maybe_request_file_approval(
            approval_store, "run-1", "Upload Resume", "resume",
            is_ambiguous=False,
        )
        assert action is None
        pending = approval_store.get_pending("run-1")
        assert len(pending) == 0

    def test_cover_letter_no_approval_needed(self, approval_store):
        action = maybe_request_file_approval(
            approval_store, "run-1", "Cover Letter", "cover_letter",
            is_ambiguous=False,
        )
        assert action is None

    def test_unknown_document_type_no_approval_by_default(self, approval_store):
        """Non-resume/cover_letter document type without ambiguity doesn't need approval by default."""
        action = maybe_request_file_approval(
            approval_store, "run-1", "Upload Certificate", "certificate",
            is_ambiguous=False,
            is_sensitive=False,
        )
        # Default policy: no approval needed for non-ambiguous, non-sensitive uploads
        assert action is None

    def test_unknown_document_type_ambiguous_needs_approval(self, approval_store):
        """Ambiguous document type always needs approval."""
        action = maybe_request_file_approval(
            approval_store, "run-1", "Upload Certificate", "certificate",
            is_ambiguous=True,
            accepted_types=["resume", "certificate"],
        )
        assert action == ApprovalAction.AMBIGUOUS_DOCUMENT_SELECTION.value

    def test_resume_no_sensitive_no_approval(self, approval_store):
        """Resume without sensitivity doesn't need approval."""
        action = maybe_request_file_approval(
            approval_store, "run-2", "Upload Resume", "resume",
            is_ambiguous=False, is_sensitive=False,
        )
        assert action is None


# ---------------------------------------------------------------------------
# Part 5: Evidence integration
# ---------------------------------------------------------------------------

class TestEvidenceIntegration:
    """Test evidence recording through the orchestrator."""

    def test_record_fill_evidence(self, evidence_store):
        record_fill_evidence(
            evidence_store, "run-1", 1, "First Name", "first_name",
            "John", "text",
        )
        records = evidence_store.get_all("run-1")
        assert len(records) >= 1
        last = records[-1]
        assert last.field_label == "First Name"
        assert last.after_value == "John"

    def test_record_file_upload_evidence(self, evidence_store):
        record_file_evidence(
            evidence_store, "run-1", 1, "Upload Resume", "resume",
            "resume.pdf", "application/pdf", True,
        )
        records = evidence_store.get_all("run-1")
        assert len(records) >= 1
        last = records[-1]
        assert last.document_type == "resume"
        assert last.uploaded_filename == "resume.pdf"
        assert last.success is True

    def test_record_file_upload_failure_evidence(self, evidence_store):
        record_file_evidence(
            evidence_store, "run-1", 1, "Upload Script", "other",
            "script.exe", "application/x-executable", False,
            validation_result="INVALID_EXTENSION",
            error="Invalid file type",
        )
        records = evidence_store.get_all("run-1")
        assert len(records) >= 1
        last = records[-1]
        assert last.success is False
        assert last.validation_result == "INVALID_EXTENSION"

    def test_no_credentials_in_evidence(self, evidence_store):
        record_fill_evidence(
            evidence_store, "run-1", 1, "Password", "password",
            "secret123", "text",
        )
        records = evidence_store.get_all("run-1")
        last = records[-1]
        assert "secret123" not in str(last.metadata)


# ---------------------------------------------------------------------------
# Part 6: Mock driver E2E with executor
# ---------------------------------------------------------------------------

class TestMockDriverE2E:
    """End-to-end tests using mock drivers through the real executor."""

    def test_simple_form_execution(self, db):
        """Test basic single-page form execution through executor."""
        import app.models  # noqa: F401
        from app.models.application_package import ApplicationPackage
        from app.models.job import Job
        from app.models.preferences import Preferences
        from app.models.profile import Profile
        from app.models.resume import Resume

        # Setup minimal data
        profile = Profile(name="Test User", email="test1@example.com", city="NYC")
        db.add(profile)
        db.flush()

        prefs = Preferences()
        db.add(prefs)
        db.flush()

        job = Job(
            title="Software Engineer",
            company="TestCo",
            url="mock://simple-form",
            application_url="mock://simple-form",
            source="linkedin",
        )
        db.add(job)
        db.flush()

        resume = Resume(
            name="Test Resume",
            file_name="resume.pdf",
            content_type="application/pdf",
            file_path="/tmp/test.pdf",
        )
        db.add(resume)
        db.flush()

        package = ApplicationPackage(
            job_id=job.id,
            profile_id=profile.id,
            selected_resume_id=resume.id,
            status="APPROVED",
            version=1,
        )
        db.add(package)
        db.flush()
        db.commit()

        from app.application_execution.executor import run_execution
        execution = run_execution(db, package, driver_name="mock", headless=True)

        # Should not be blocked (simple-form is authenticated)
        assert execution.status != base.STATUS_BLOCKED
        assert execution.platform is not None
        assert execution.execution_mode is not None

    def test_resume_upload_execution(self, db):
        """Test execution with resume upload."""
        import app.models  # noqa: F401
        from app.models.application_package import ApplicationPackage
        from app.models.job import Job
        from app.models.preferences import Preferences
        from app.models.profile import Profile
        from app.models.resume import Resume

        profile = Profile(name="Test User", email="upload@example.com", city="NYC")
        db.add(profile)
        db.flush()

        prefs = Preferences()
        db.add(prefs)
        db.flush()

        job = Job(
            title="Software Engineer",
            company="TestCo",
            url="mock://resume-upload",
            application_url="mock://resume-upload",
            source="linkedin",
        )
        db.add(job)
        db.flush()

        resume = Resume(
            name="Test Resume",
            file_name="resume.pdf",
            content_type="application/pdf",
            file_path="/tmp/test.pdf",
        )
        db.add(resume)
        db.flush()

        package = ApplicationPackage(
            job_id=job.id,
            profile_id=profile.id,
            selected_resume_id=resume.id,
            status="APPROVED",
            version=1,
        )
        db.add(package)
        db.flush()
        db.commit()

        from app.application_execution.executor import run_execution
        execution = run_execution(db, package, driver_name="mock", headless=True)

        assert execution.status != base.STATUS_BLOCKED

    def test_captcha_blocked(self, db):
        """Test CAPTCHA detection blocks execution."""
        import app.models  # noqa: F401
        from app.models.application_package import ApplicationPackage
        from app.models.job import Job
        from app.models.preferences import Preferences
        from app.models.profile import Profile

        profile = Profile(name="Test User", email="captcha@example.com")
        db.add(profile)
        db.flush()

        prefs = Preferences()
        db.add(prefs)
        db.flush()

        job = Job(
            title="Software Engineer",
            company="TestCo",
            url="mock://captcha",
            application_url="mock://captcha",
            source="linkedin",
        )
        db.add(job)
        db.flush()

        package = ApplicationPackage(
            job_id=job.id,
            profile_id=profile.id,
            status="APPROVED",
            version=1,
        )
        db.add(package)
        db.flush()
        db.commit()

        from app.application_execution.executor import run_execution
        execution = run_execution(db, package, driver_name="mock", headless=True)

        assert execution.status == base.STATUS_BLOCKED

    def test_auth_required_blocks(self, db):
        """Test authentication required blocks execution."""
        import app.models  # noqa: F401
        from app.models.application_package import ApplicationPackage
        from app.models.job import Job
        from app.models.preferences import Preferences
        from app.models.profile import Profile

        profile = Profile(name="Test User", email="auth@example.com")
        db.add(profile)
        db.flush()

        prefs = Preferences()
        db.add(prefs)
        db.flush()

        job = Job(
            title="Software Engineer",
            company="TestCo",
            url="mock://auth-password",
            application_url="mock://auth-password",
            source="linkedin",
        )
        db.add(job)
        db.flush()

        package = ApplicationPackage(
            job_id=job.id,
            profile_id=profile.id,
            status="APPROVED",
            version=1,
        )
        db.add(package)
        db.flush()
        db.commit()

        from app.application_execution.executor import run_execution
        execution = run_execution(db, package, driver_name="mock", headless=True)

        assert execution.status == base.STATUS_AWAITING_USER

    def test_mfa_required_blocks(self, db):
        """Test MFA required blocks execution."""
        import app.models  # noqa: F401
        from app.models.application_package import ApplicationPackage
        from app.models.job import Job
        from app.models.preferences import Preferences
        from app.models.profile import Profile

        profile = Profile(name="Test User", email="mfa@example.com")
        db.add(profile)
        db.flush()

        prefs = Preferences()
        db.add(prefs)
        db.flush()

        job = Job(
            title="Software Engineer",
            company="TestCo",
            url="mock://auth-mfa",
            application_url="mock://auth-mfa",
            source="linkedin",
        )
        db.add(job)
        db.flush()

        package = ApplicationPackage(
            job_id=job.id,
            profile_id=profile.id,
            status="APPROVED",
            version=1,
        )
        db.add(package)
        db.flush()
        db.commit()

        from app.application_execution.executor import run_execution
        execution = run_execution(db, package, driver_name="mock", headless=True)

        assert execution.status == base.STATUS_AWAITING_USER

    def test_new_question_blocks(self, db):
        """Test new question detection blocks execution."""
        import app.models  # noqa: F401
        from app.models.application_package import ApplicationPackage
        from app.models.job import Job
        from app.models.preferences import Preferences
        from app.models.profile import Profile

        profile = Profile(name="Test User", email="newq@example.com")
        db.add(profile)
        db.flush()

        prefs = Preferences()
        db.add(prefs)
        db.flush()

        job = Job(
            title="Software Engineer",
            company="TestCo",
            url="mock://new-question",
            application_url="mock://new-question",
            source="linkedin",
        )
        db.add(job)
        db.flush()

        package = ApplicationPackage(
            job_id=job.id,
            profile_id=profile.id,
            status="APPROVED",
            version=1,
        )
        db.add(package)
        db.flush()
        db.commit()

        from app.application_execution.executor import run_execution
        execution = run_execution(db, package, driver_name="mock", headless=True)

        assert execution.status == base.STATUS_AWAITING_USER


# ---------------------------------------------------------------------------
# Part 7: Safety invariants
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    """Verify safety invariants are maintained in the execution pipeline."""

    def test_never_auto_accept_terms(self, profile_ctx):
        raw = DetectedField(key="cb1", label="I agree to the Terms", kind="checkbox")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.classification == REQUIRES_REVIEW
        assert f.value is None

    def test_never_auto_consent(self, profile_ctx):
        raw = DetectedField(key="cb2", label="Data Consent", kind="checkbox")
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.classification == REQUIRES_REVIEW
        assert f.value is None

    def test_gender_never_guessed(self, profile_ctx):
        raw = DetectedField(
            key="g1", label="Gender", kind="select",
            options=["Male", "Female", "Other"],
        )
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.classification == REQUIRES_REVIEW

    def test_relocation_never_guessed(self, profile_ctx):
        raw = DetectedField(
            key="rel1", label="Relocation", kind="select",
            options=["Yes", "No"],
        )
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.classification == REQUIRES_REVIEW

    def test_file_upload_requires_review(self, profile_ctx):
        raw = DetectedField(key="fr1", label="Upload Resume", kind="file", required=True)
        result = map_fields([raw], profile_ctx)
        f = result.fields[0]
        assert f.classification == REQUIRES_REVIEW

    def test_ambiguous_file_needs_approval(self, approval_store):
        action = maybe_request_file_approval(
            approval_store, "run-1", "Documents", "other",
            is_ambiguous=True,
            accepted_types=["resume", "cover_letter"],
        )
        assert action is not None
        pending = approval_store.get_pending("run-1")
        assert len(pending) == 1

    def test_no_credential_in_evidence(self, evidence_store):
        record_fill_evidence(
            evidence_store, "run-1", 1, "Password", "password",
            "secret123", "text",
        )
        records = evidence_store.get_all("run-1")
        assert "secret123" not in str(records[-1].metadata)


# ---------------------------------------------------------------------------
# Part 8: Single-page regression
# ---------------------------------------------------------------------------

class TestSinglePageRegression:
    """Regression tests for single-page execution."""

    def test_map_fields_simple(self, profile_ctx):
        raw_fields = [
            DetectedField(key="f1", label="First Name", kind="text", required=True),
            DetectedField(key="f2", label="Last Name", kind="text", required=True),
            DetectedField(key="f3", label="Email", kind="text", required=True),
        ]
        result = map_fields(raw_fields, profile_ctx)
        assert result.known_count == 3
        assert result.new_questions == []

    def test_map_fields_with_unknown(self, profile_ctx):
        raw_fields = [
            DetectedField(key="f1", label="First Name", kind="text"),
            DetectedField(key="u1", label="SSN", kind="text", required=True),
        ]
        result = map_fields(raw_fields, profile_ctx)
        assert result.known_count == 1
        assert len(result.new_questions) == 1

    def test_map_fields_mixed_kinds(self, profile_ctx):
        raw_fields = [
            DetectedField(key="f1", label="First Name", kind="text"),
            DetectedField(key="s1", label="Experience", kind="select",
                          options=["0-2 years", "3-5 years"]),
            DetectedField(key="r1", label="Employment Type", kind="radio",
                          options=["Full-time", "Part-time"]),
        ]
        result = map_fields(raw_fields, profile_ctx)
        assert result.known_count == 3

    def test_fill_result_known(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://simple-form")
        driver.open(driver.url)
        result = driver.fill("f1", "John")
        assert result.status == "KNOWN"

    def test_submission_confirmed(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://confirmation")
        driver.open(driver.url)
        result = driver.submit()
        assert result.confirmed is True

    def test_submission_failed(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://failed-submit")
        driver.open(driver.url)
        result = driver.submit()
        assert result.failure is True

    def test_captcha_detected(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://captcha")
        driver.open(driver.url)
        assert driver.detect_captcha() is True

    def test_login_detected(self):
        from app.application_execution.browser import MockBrowserDriver
        driver = MockBrowserDriver("mock://login-required")
        driver.open(driver.url)
        assert driver.detect_login() is True
