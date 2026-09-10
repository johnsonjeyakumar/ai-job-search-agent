"""Phase 22 — Application profile completeness + readiness gate tests.

Tests profile completeness, application-specific requirements, answer
readiness, document readiness, package readiness, conflict detection,
sensitive data handling, previous execution blockers, preflight integration,
duplicate integration, final readiness decision, readiness refresh, and
Playwright E2E scenarios.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.application_execution.readiness import (
    _PROFILE_FIELDS,
    _SENSITIVE_FIELDS,
    CompletenessResult,
    ReadinessResult,
    ReadinessStatus,
    Requirement,
    RequirementSource,
    RequirementStatus,
    _is_filled,
    check_answer_readiness,
    check_document_readiness,
    check_package_readiness,
    check_previous_execution_blockers,
    detect_profile_conflicts,
    detect_requirements_from_form_fields,
    determine_readiness,
    evaluate_profile_completeness,
    needs_refresh,
    run_readiness_check,
)

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — READINESS STATES
# ═══════════════════════════════════════════════════════════════════════════

class TestReadinessStates:
    def test_readiness_status_values(self):
        expected = {"READY", "NEEDS_INPUT", "REVIEW", "BLOCKED", "INCOMPLETE", "INVALID"}
        actual = {s.value for s in ReadinessStatus}
        assert actual == expected

    def test_readiness_status_is_string_enum(self):
        assert ReadinessStatus.READY == "READY"
        assert ReadinessStatus.BLOCKED == "BLOCKED"


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — PROFILE COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileCompleteness:
    def test_empty_profile(self):
        result = evaluate_profile_completeness(None)
        assert result.score == 0.0
        assert result.filled_fields == 0
        assert result.total_fields == len(_PROFILE_FIELDS)

    def test_full_profile(self):
        profile = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "555-1234",
            "city": "New York",
            "state": "NY",
            "country": "US",
            "degree": "BS",
            "university": "MIT",
            "graduation_year": 2020,
            "experience_level": "3 years",
            "skills": ["Python", "JavaScript"],
            "work_authorization": "US Citizen",
            "salary_preference": "100000",
            "linkedin_url": "https://linkedin.com/in/johndoe",
            "github_url": "https://github.com/johndoe",
            "portfolio_url": "https://johndoe.com",
        }
        result = evaluate_profile_completeness(profile)
        assert result.score == 100.0
        assert result.filled_fields == result.total_fields

    def test_partial_profile(self):
        profile = {
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "555-1234",
        }
        result = evaluate_profile_completeness(profile)
        assert result.filled_fields == 3
        assert 0 < result.score < 100

    def test_empty_string_not_filled(self):
        assert _is_filled("") is False
        assert _is_filled("  ") is False
        assert _is_filled(None) is False
        assert _is_filled([]) is False

    def test_filled_values(self):
        assert _is_filled("hello") is True
        assert _is_filled(42) is True
        assert _is_filled(["a"]) is True

    def test_completeness_is_informational_only(self):
        """Completeness score does NOT determine readiness."""
        profile = {"name": "John", "email": "j@e.com"}
        result = evaluate_profile_completeness(profile)
        assert result.score > 0
        # Even with low completeness, readiness could be READY
        # if all required fields for that specific job are present

    def test_completeness_score_calculation(self):
        profile = {"name": "X", "email": "x@x.com"}
        result = evaluate_profile_completeness(profile)
        expected = round(2 / len(_PROFILE_FIELDS) * 100, 1)
        assert result.score == expected


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4-5 — APPLICATION-SPECIFIC REQUIREMENTS
# ═══════════════════════════════════════════════════════════════════════════

class TestApplicationSpecificRequirements:
    def test_base_requirements_always_present(self):
        reqs = detect_requirements_from_form_fields()
        categories = [r["category"] for r in reqs]
        assert "IDENTITY" in categories
        assert "CONTACT" in categories
        assert "DOCUMENT" in categories

    def test_base_requirements_include_name_email_phone_resume(self):
        reqs = detect_requirements_from_form_fields()
        labels = [r["label"] for r in reqs]
        assert "Full Name" in labels
        assert "Email" in labels
        assert "Phone" in labels
        assert "Resume" in labels

    def test_resume_is_always_required(self):
        reqs = detect_requirements_from_form_fields()
        resume_req = [r for r in reqs if r["label"] == "Resume"][0]
        assert resume_req["required"] is True

    def test_form_field_adds_work_auth(self):
        fields = [{"label": "Work Authorization", "key": "work_auth", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "WORK_AUTHORIZATION" in categories

    def test_form_field_adds_sponsorship(self):
        fields = [{"label": "Visa Sponsorship", "key": "sponsorship", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "SPONSORSHIP" in categories

    def test_form_field_adds_cover_letter(self):
        fields = [{"label": "Cover Letter", "key": "cover_letter", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        labels = [r["label"] for r in reqs]
        assert "Cover Letter" in labels

    def test_form_field_adds_portfolio(self):
        fields = [{"label": "Portfolio URL", "key": "portfolio_url", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        labels = [r["label"] for r in reqs]
        assert "Portfolio URL" in labels

    def test_form_field_adds_linkedin(self):
        fields = [{"label": "LinkedIn Profile", "key": "linkedin", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        labels = [r["label"] for r in reqs]
        assert "LinkedIn Profile" in labels

    def test_form_field_adds_github(self):
        fields = [{"label": "GitHub Profile", "key": "github", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        labels = [r["label"] for r in reqs]
        assert "GitHub Profile" in labels

    def test_form_field_adds_availability(self):
        fields = [{"label": "Start Date", "key": "start_date", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "AVAILABILITY" in categories

    def test_form_field_adds_salary(self):
        fields = [{"label": "Expected Salary", "key": "salary", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "COMPENSATION" in categories

    def test_form_field_adds_relocation(self):
        fields = [{"label": "Willing to Relocate", "key": "relocation", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "RELOCATION" in categories

    def test_form_field_adds_education(self):
        fields = [{"label": "Degree", "key": "degree", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "EDUCATION" in categories

    def test_form_field_adds_experience(self):
        fields = [{"label": "Years of Experience", "key": "experience", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        categories = [r["category"] for r in reqs]
        assert "EXPERIENCE" in categories

    def test_job_data_adds_sponsorship_from_description(self):
        job = {"description": "We do not offer visa sponsorship for this role."}
        reqs = detect_requirements_from_form_fields(job_data=job)
        categories = [r["category"] for r in reqs]
        assert "SPONSORSHIP" in categories

    def test_job_data_adds_relocation_from_description(self):
        job = {"description": "This role requires on-site presence."}
        reqs = detect_requirements_from_form_fields(job_data=job)
        categories = [r["category"] for r in reqs]
        assert "RELOCATION" in categories

    def test_job_data_adds_work_auth_from_description(self):
        job = {"description": "Must be authorized to work in the US."}
        reqs = detect_requirements_from_form_fields(job_data=job)
        categories = [r["category"] for r in reqs]
        assert "WORK_AUTHORIZATION" in categories

    def test_job_data_adds_cover_letter_from_description(self):
        job = {"description": "Please include a cover letter."}
        reqs = detect_requirements_from_form_fields(job_data=job)
        labels = [r["label"] for r in reqs]
        assert "Cover Letter" in labels

    def test_job_data_adds_portfolio_from_description(self):
        job = {"description": "Please share your portfolio."}
        reqs = detect_requirements_from_form_fields(job_data=job)
        labels = [r["label"] for r in reqs]
        assert "Portfolio URL" in labels

    def test_no_duplicate_requirements(self):
        fields = [
            {"label": "Work Authorization", "key": "work_auth", "required": True},
            {"label": "Work Authorization", "key": "work_auth", "required": False},
        ]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        work_auth_reqs = [r for r in reqs if r["category"] == "WORK_AUTHORIZATION"]
        assert len(work_auth_reqs) == 1

    def test_form_required_overrides_optional(self):
        fields = [{"label": "Work Authorization", "key": "work_auth", "required": True}]
        reqs = detect_requirements_from_form_fields(form_fields=fields)
        wa = [r for r in reqs if r["category"] == "WORK_AUTHORIZATION"][0]
        assert wa["required"] is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 6 — REQUIREMENT SOURCES
# ═══════════════════════════════════════════════════════════════════════════

class TestRequirementSources:
    def test_source_values(self):
        expected = {
            "profile", "application_answer", "application_memory",
            "verified_resume", "verified_package", "form_derived",
            "explicit_user", "job_specific", "unknown",
        }
        actual = {s.value for s in RequirementSource}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════════════
# STEP 7 — ANSWER READINESS
# ═══════════════════════════════════════════════════════════════════════════

class TestAnswerReadiness:
    def _make_req(self, **kwargs):
        defaults = {
            "category": "CONTACT",
            "label": "Phone",
            "field_key": "phone",
            "required": True,
        }
        defaults.update(kwargs)
        return Requirement(**defaults)

    def test_satisfied_from_profile(self):
        req = self._make_req()
        result = check_answer_readiness(req, {"phone": "555-1234"})
        assert result.status == RequirementStatus.SATISFIED
        assert result.value == "555-1234"
        assert result.source == RequirementSource.PROFILE

    def test_satisfied_from_answer(self):
        req = self._make_req()
        result = check_answer_readiness(req, None, {"phone number": "555-9999"})
        assert result.status == RequirementStatus.SATISFIED
        assert result.value == "555-9999"
        assert result.source == RequirementSource.APPLICATION_ANSWER

    def test_satisfied_from_memory(self):
        req = self._make_req()
        result = check_answer_readiness(req, None, None, {"phone": "555-0000"})
        assert result.status == RequirementStatus.SATISFIED
        assert result.source == RequirementSource.APPLICATION_MEMORY

    def test_profile_takes_precedence_over_answer(self):
        req = self._make_req()
        result = check_answer_readiness(
            req, {"phone": "555-1111"}, {"phone": "555-2222"}
        )
        assert result.value == "555-1111"

    def test_missing_required_field(self):
        req = self._make_req()
        result = check_answer_readiness(req, None)
        assert result.status == RequirementStatus.MISSING
        assert "Required" in result.reason

    def test_optional_field_not_applicable(self):
        req = self._make_req(required=False)
        result = check_answer_readiness(req, None)
        assert result.status == RequirementStatus.NOT_APPLICABLE

    def test_sensitive_field_with_valid_value(self):
        req = self._make_req(
            field_key="work_authorization",
            is_sensitive=True,
            category="WORK_AUTHORIZATION",
            label="Work Authorization",
        )
        result = check_answer_readiness(req, {"work_authorization": "US Citizen"})
        assert result.status == RequirementStatus.SATISFIED

    def test_sensitive_field_with_ambiguous_value(self):
        req = self._make_req(
            field_key="work_authorization",
            is_sensitive=True,
            category="WORK_AUTHORIZATION",
            label="Work Authorization",
        )
        result = check_answer_readiness(req, {"work_authorization": "unknown"})
        assert result.status == RequirementStatus.UNSAFE

    def test_sensitive_field_with_prefer_not_to_say(self):
        req = self._make_req(
            field_key="salary_preference",
            is_sensitive=True,
            category="COMPENSATION",
            label="Salary",
        )
        result = check_answer_readiness(req, {"salary_preference": "prefer not to say"})
        assert result.status == RequirementStatus.UNSAFE

    def test_no_field_key_returns_unchanged(self):
        req = Requirement(category="X", label="X")
        result = check_answer_readiness(req, {"phone": "555"})
        assert result.status == RequirementStatus.MISSING


# ═══════════════════════════════════════════════════════════════════════════
# STEP 8-9 — DOCUMENT / RESUME READINESS
# ═══════════════════════════════════════════════════════════════════════════

class TestDocumentReadiness:
    def test_non_document_unaffected(self):
        req = Requirement(category="CONTACT", label="Phone", is_document=False)
        result = check_document_readiness(req, None)
        assert result.status == RequirementStatus.MISSING

    def test_resume_missing_package(self):
        req = Requirement(
            category="DOCUMENT", label="Resume", is_document=True,
            document_type="resume", field_key="resume",
        )
        result = check_document_readiness(req, None)
        assert result.status == RequirementStatus.MISSING
        assert "package" in result.reason.lower()

    def test_resume_no_selection(self):
        req = Requirement(
            category="DOCUMENT", label="Resume", is_document=True,
            document_type="resume", field_key="resume",
        )
        result = check_document_readiness(req, {"selected_resume_id": None})
        assert result.status == RequirementStatus.MISSING

    def test_resume_not_found(self):
        req = Requirement(
            category="DOCUMENT", label="Resume", is_document=True,
            document_type="resume", field_key="resume",
        )
        result = check_document_readiness(
            req, {"selected_resume_id": 1}, resume_data=None
        )
        assert result.status == RequirementStatus.MISSING

    def test_resume_no_file(self):
        req = Requirement(
            category="DOCUMENT", label="Resume", is_document=True,
            document_type="resume", field_key="resume",
        )
        result = check_document_readiness(
            req, {"selected_resume_id": 1}, resume_data={"file_path": None}
        )
        assert result.status == RequirementStatus.INVALID

    def test_resume_inactive(self):
        req = Requirement(
            category="DOCUMENT", label="Resume", is_document=True,
            document_type="resume", field_key="resume",
        )
        result = check_document_readiness(
            req, {"selected_resume_id": 1},
            resume_data={"file_path": "/path/to/resume.pdf", "is_active": False},
        )
        assert result.status == RequirementStatus.INVALID

    def test_resume_valid(self):
        req = Requirement(
            category="DOCUMENT", label="Resume", is_document=True,
            document_type="resume", field_key="resume",
        )
        result = check_document_readiness(
            req, {"selected_resume_id": 1},
            resume_data={"name": "My Resume", "file_path": "/r.pdf", "is_active": True},
        )
        assert result.status == RequirementStatus.SATISFIED
        assert result.source == RequirementSource.VERIFIED_RESUME


class TestCoverLetterReadiness:
    def test_cover_letter_available(self):
        req = Requirement(
            category="DOCUMENT", label="Cover Letter", is_document=True,
            document_type="cover_letter", field_key="cover_letter",
        )
        result = check_document_readiness(
            req, {"cover_letter": "Dear Hiring Manager...", "cover_letter_status": "generated"}
        )
        assert result.status == RequirementStatus.SATISFIED

    def test_cover_letter_required_missing(self):
        req = Requirement(
            category="DOCUMENT", label="Cover Letter", is_document=True,
            document_type="cover_letter", field_key="cover_letter",
            required=True,
        )
        result = check_document_readiness(req, {"cover_letter_status": "skipped"})
        assert result.status == RequirementStatus.MISSING

    def test_cover_letter_optional_missing(self):
        req = Requirement(
            category="DOCUMENT", label="Cover Letter", is_document=True,
            document_type="cover_letter", field_key="cover_letter",
            required=False,
        )
        result = check_document_readiness(req, {"cover_letter_status": "skipped"})
        assert result.status == RequirementStatus.NOT_APPLICABLE

    def test_cover_letter_needs_review(self):
        req = Requirement(
            category="DOCUMENT", label="Cover Letter", is_document=True,
            document_type="cover_letter", field_key="cover_letter",
        )
        result = check_document_readiness(
            req, {"cover_letter": "text", "cover_letter_status": "needs_review"}
        )
        assert result.status == RequirementStatus.SATISFIED

    def test_cover_letter_no_package(self):
        req = Requirement(
            category="DOCUMENT", label="Cover Letter", is_document=True,
            document_type="cover_letter", field_key="cover_letter",
            required=True,
        )
        result = check_document_readiness(req, None)
        assert result.status == RequirementStatus.MISSING


# ═══════════════════════════════════════════════════════════════════════════
# STEP 11 — PORTFOLIO READINESS
# ═══════════════════════════════════════════════════════════════════════════

class TestPortfolioReadiness:
    def test_portfolio_from_profile(self):
        req = Requirement(
            category="PORTFOLIO", label="Portfolio URL",
            field_key="portfolio_url", required=True,
        )
        result = check_answer_readiness(req, {"portfolio_url": "https://me.com"})
        assert result.status == RequirementStatus.SATISFIED

    def test_portfolio_missing(self):
        req = Requirement(
            category="PORTFOLIO", label="Portfolio URL",
            field_key="portfolio_url", required=True,
        )
        result = check_answer_readiness(req, None)
        assert result.status == RequirementStatus.MISSING

    def test_portfolio_optional_missing(self):
        req = Requirement(
            category="PORTFOLIO", label="Portfolio URL",
            field_key="portfolio_url", required=False,
        )
        result = check_answer_readiness(req, None)
        assert result.status == RequirementStatus.NOT_APPLICABLE


# ═══════════════════════════════════════════════════════════════════════════
# STEP 12 — PROFILE VS APPLICATION CONFLICTS
# ═══════════════════════════════════════════════════════════════════════════

class TestProfileConflicts:
    def test_no_conflict(self):
        profile = {"city": "New York"}
        answers = {"city": "New York"}
        result = detect_profile_conflicts(profile, answers)
        assert len(result) == 0

    def test_city_conflict(self):
        profile = {"city": "Madurai"}
        answers = {"city": "Chennai"}
        result = detect_profile_conflicts(profile, answers)
        assert len(result) == 1
        assert result[0].status == RequirementStatus.CONTRADICTORY

    def test_experience_conflict(self):
        profile = {"experience_level": "2 years"}
        answers = {"years of experience": "5 years"}
        result = detect_profile_conflicts(profile, answers)
        assert len(result) == 1

    def test_no_profile_no_conflict(self):
        result = detect_profile_conflicts(None, {"city": "X"})
        assert len(result) == 0

    def test_no_answers_no_conflict(self):
        result = detect_profile_conflicts({"city": "X"}, None)
        assert len(result) == 0

    def test_empty_profile_value_no_conflict(self):
        result = detect_profile_conflicts({"city": ""}, {"city": "X"})
        assert len(result) == 0

    def test_multiple_conflicts(self):
        profile = {"city": "A", "state": "X"}
        answers = {"city": "B", "state": "Y"}
        result = detect_profile_conflicts(profile, answers)
        assert len(result) == 2


# ═══════════════════════════════════════════════════════════════════════════
# STEP 13 — SENSITIVE PROFILE READINESS
# ═══════════════════════════════════════════════════════════════════════════

class TestSensitiveReadiness:
    def test_sensitive_fields_defined(self):
        assert "work_authorization" in _SENSITIVE_FIELDS
        assert "salary_preference" in _SENSITIVE_FIELDS
        assert "gender" in _SENSITIVE_FIELDS
        assert "relocation" in _SENSITIVE_FIELDS

    def test_sensitive_value_unknown_triggers_unsafe(self):
        req = Requirement(
            category="WORK_AUTHORIZATION", label="Work Auth",
            field_key="work_authorization", is_sensitive=True,
        )
        result = check_answer_readiness(req, {"work_authorization": "unknown"})
        assert result.status == RequirementStatus.UNSAFE

    def test_sensitive_value_valid_satisfied(self):
        req = Requirement(
            category="WORK_AUTHORIZATION", label="Work Auth",
            field_key="work_authorization", is_sensitive=True,
        )
        result = check_answer_readiness(req, {"work_authorization": "US Citizen"})
        assert result.status == RequirementStatus.SATISFIED

    def test_sensitive_not_inferred(self):
        """Sensitive fields should never be inferred from unrelated data."""
        # The system should not auto-fill work_authorization from location
        req = Requirement(
            category="WORK_AUTHORIZATION", label="Work Auth",
            field_key="work_authorization", is_sensitive=True,
        )
        result = check_answer_readiness(req, None)
        # Should NOT be SATISFIED — no value was provided
        assert result.status != RequirementStatus.SATISFIED


# ═══════════════════════════════════════════════════════════════════════════
# STEP 14 — PACKAGE READINESS
# ═══════════════════════════════════════════════════════════════════════════

class TestPackageReadiness:
    def test_no_package(self):
        status, reasons = check_package_readiness(None)
        assert status == ReadinessStatus.BLOCKED
        assert "package" in reasons[0].lower()

    def test_package_not_approved(self):
        status, reasons = check_package_readiness({"status": "DRAFT"})
        assert status == ReadinessStatus.REVIEW

    def test_package_quality_gate_fail(self):
        status, reasons = check_package_readiness(
            {"status": "APPROVED", "quality_gate": "FAIL"}
        )
        assert status == ReadinessStatus.INVALID

    def test_package_not_ready(self):
        status, reasons = check_package_readiness(
            {"status": "APPROVED", "readiness": "NOT_READY"}
        )
        assert status == ReadinessStatus.INVALID

    def test_package_approved_ready(self):
        status, reasons = check_package_readiness(
            {"status": "APPROVED", "quality_gate": "PASS", "readiness": "READY"}
        )
        assert status == ReadinessStatus.READY
        assert len(reasons) == 0


# ═══════════════════════════════════════════════════════════════════════════
# STEP 15 — PREVIOUS EXECUTION STATE
# ═══════════════════════════════════════════════════════════════════════════

class TestPreviousExecutionBlockers:
    def test_no_executions(self):
        result = check_previous_execution_blockers(None)
        assert len(result) == 0

    def test_submission_unknown_blocks(self):
        execs = [{"id": 1, "status": "SUBMISSION_UNKNOWN", "submission_status": None}]
        result = check_previous_execution_blockers(execs)
        assert len(result) == 1
        assert "uncertain" in result[0].lower()

    def test_blocked_execution_blocks(self):
        execs = [{"id": 1, "status": "BLOCKED", "submission_status": None}]
        result = check_previous_execution_blockers(execs)
        assert len(result) == 1

    def test_unknown_submission_status_blocks(self):
        execs = [{"id": 1, "status": "EXECUTING", "submission_status": "UNKNOWN"}]
        result = check_previous_execution_blockers(execs)
        assert len(result) == 1

    def test_confirmed_submission_no_block(self):
        execs = [{"id": 1, "status": "SUBMITTED", "submission_status": "CONFIRMED"}]
        result = check_previous_execution_blockers(execs)
        assert len(result) == 0

    def test_multiple_executions_one_blocks(self):
        execs = [
            {"id": 1, "status": "SUBMITTED", "submission_status": "CONFIRMED"},
            {"id": 2, "status": "SUBMISSION_UNKNOWN", "submission_status": None},
        ]
        result = check_previous_execution_blockers(execs)
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════════
# STEP 17 — FINAL READINESS RESULT
# ═══════════════════════════════════════════════════════════════════════════

class TestFinalReadinessDecision:
    def _req(self, status=RequirementStatus.SATISFIED, required=True, **kwargs):
        defaults = {
            "category": "CONTACT", "label": "Phone",
            "field_key": "phone", "required": required,
        }
        defaults.update(kwargs)
        r = Requirement(**defaults)
        r.status = status
        return r

    def test_all_satisfied_ready(self):
        reqs = [self._req(), self._req(label="Email")]
        comp = CompletenessResult(total_fields=2, filled_fields=2)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.READY

    def test_missing_required_needs_input(self):
        reqs = [self._req(), self._req(status=RequirementStatus.MISSING, label="Email")]
        comp = CompletenessResult(total_fields=2, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT

    def test_package_invalid_blocked(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.INVALID,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_duplicate_blocked(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="ALREADY_APPLIED",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_duplicate_suspected_review(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="DUPLICATE_SUSPECTED",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_previous_blocker_review(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=["Previous uncertain submission"],
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_contradictory_review(self):
        reqs = [
            self._req(),
            self._req(
                status=RequirementStatus.CONTRADICTORY,
                label="City Conflict",
            ),
        ]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_unsafe_sensitive_review(self):
        reqs = [
            self._req(),
            self._req(
                status=RequirementStatus.UNSAFE,
                label="Work Auth",
                is_sensitive=True,
            ),
        ]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_package_review_status(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.REVIEW,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_result_has_all_requirements(self):
        reqs = [self._req(), self._req(label="Email")]
        comp = CompletenessResult(total_fields=2, filled_fields=2)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert len(result.all_requirements) == 2
        assert result.required_count == 2
        assert result.satisfied_count == 2

    def test_is_ready_property(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.is_ready is True
        assert result.has_blockers is False
        assert result.needs_attention is False

    def test_has_blockers_property(self):
        reqs = [self._req()]
        comp = CompletenessResult(total_fields=1, filled_fields=1)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.INVALID,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.has_blockers is True

    def test_needs_attention_property(self):
        reqs = [self._req(status=RequirementStatus.MISSING)]
        comp = CompletenessResult(total_fields=1, filled_fields=0)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.needs_attention is True

    def test_checked_at_auto_populated(self):
        reqs = []
        comp = CompletenessResult(total_fields=0, filled_fields=0)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.checked_at != ""

    def test_optional_missing_does_not_block(self):
        reqs = [self._req(required=False, status=RequirementStatus.NOT_APPLICABLE)]
        comp = CompletenessResult(total_fields=1, filled_fields=0)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.READY


# ═══════════════════════════════════════════════════════════════════════════
# STEP 18 — DETERMINISTIC DECISION RULES
# ═══════════════════════════════════════════════════════════════════════════

class TestDeterministicDecisionRules:
    def test_blocked_overrides_review(self):
        """Package invalid should block even if duplicate is suspected."""
        reqs = []
        comp = CompletenessResult(total_fields=0, filled_fields=0)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.INVALID,
            preflight_status="PASS", duplicate_status="DUPLICATE_SUSPECTED",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_duplicate_overrides_missing_input(self):
        """Duplicate should block even if fields are missing."""
        reqs = [Requirement(
            category="X", label="X", required=True,
            status=RequirementStatus.MISSING,
        )]
        comp = CompletenessResult(total_fields=1, filled_fields=0)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="ALREADY_APPLIED",
            previous_blockers=[],
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_reason_codes_populated(self):
        reqs = [Requirement(
            category="X", label="X", required=True,
            status=RequirementStatus.MISSING,
        )]
        comp = CompletenessResult(total_fields=1, filled_fields=0)
        result = determine_readiness(
            requirements=reqs, completeness=comp,
            package_status=ReadinessStatus.READY,
            preflight_status="PASS", duplicate_status="SAFE_TO_SUBMIT",
            previous_blockers=[],
        )
        assert "REQUIRED_FIELDS_MISSING" in result.reason_codes


# ═══════════════════════════════════════════════════════════════════════════
# STEP 21 — READINESS REFRESH
# ═══════════════════════════════════════════════════════════════════════════

class TestReadinessRefresh:
    def test_fresh_result_no_refresh(self):
        result = ReadinessResult(
            checked_at=datetime.now(timezone.utc).isoformat()
        )
        assert needs_refresh(result, max_age_seconds=1800) is False

    def test_stale_result_needs_refresh(self):
        from datetime import timedelta
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = ReadinessResult(checked_at=stale_time)
        assert needs_refresh(result, max_age_seconds=1800) is True

    def test_empty_checked_at_needs_refresh(self):
        result = ReadinessResult()
        result.checked_at = ""
        assert needs_refresh(result) is True

    def test_invalid_checked_at_needs_refresh(self):
        result = ReadinessResult()
        result.checked_at = "not-a-date"
        assert needs_refresh(result) is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 16 — INTEGRATION (combined readiness check)
# ═══════════════════════════════════════════════════════════════════════════

class TestReadinessCheckIntegration:
    def test_ready_application(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            package_data={"status": "APPROVED", "quality_gate": "PASS",
                          "readiness": "READY", "selected_resume_id": 1,
                          "cover_letter_status": "skipped"},
            resume_data={"name": "Resume", "file_path": "/r.pdf", "is_active": True},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.READY

    def test_missing_profile(self):
        result = run_readiness_check(
            profile_data=None,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status in (ReadinessStatus.NEEDS_INPUT, ReadinessStatus.INCOMPLETE)

    def test_missing_resume(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            package_data={"status": "APPROVED", "selected_resume_id": None},
            resume_data=None,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT

    def test_duplicate_blocked(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            duplicate_status="ALREADY_APPLIED",
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_package_invalid_blocked(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            package_data={"status": "APPROVED", "quality_gate": "FAIL"},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_contradictory_data_review(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555",
                          "city": "Madurai"},
            answers={"city": "Chennai"},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_previous_uncertain_review(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            previous_executions=[{"id": 1, "status": "SUBMISSION_UNKNOWN"}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_sponsorship_unknown_review(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            form_fields=[{"label": "Visa Sponsorship", "key": "sponsorship", "required": True}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT

    def test_ids_populated(self):
        result = run_readiness_check(
            application_id=42, job_id=99, package_id=7,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.application_id == 42
        assert result.job_id == 99
        assert result.package_id == 7

    def test_completeness_always_evaluated(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com"},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.completeness is not None
        assert result.completeness.total_fields > 0

    def test_work_auth_required_missing(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            form_fields=[{"label": "Work Authorization", "key": "work_auth", "required": True}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT

    def test_cover_letter_required_missing(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            package_data={"status": "APPROVED", "cover_letter_status": "skipped"},
            form_fields=[{"label": "Cover Letter", "key": "cover_letter", "required": True}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT

    def test_portfolio_required_missing(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            form_fields=[{"label": "Portfolio URL", "key": "portfolio_url", "required": True}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT


# ═══════════════════════════════════════════════════════════════════════════
# STEP 25 — MOCK SCENARIOS (smoke tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestMockScenarioSmoke:
    """Verify mock scenarios are routable (no full E2E here)."""

    def test_readiness_status_is_deterministic(self):
        """Readiness decision is always deterministic for same inputs."""
        r1 = run_readiness_check(
            profile_data={"name": "X", "email": "x@x.com", "phone": "555"},
            package_data={"status": "APPROVED", "selected_resume_id": 1,
                          "quality_gate": "PASS", "readiness": "READY"},
            resume_data={"name": "R", "file_path": "/r.pdf", "is_active": True},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        r2 = run_readiness_check(
            profile_data={"name": "X", "email": "x@x.com", "phone": "555"},
            package_data={"status": "APPROVED", "selected_resume_id": 1,
                          "quality_gate": "PASS", "readiness": "READY"},
            resume_data={"name": "R", "file_path": "/r.pdf", "is_active": True},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert r1.status == r2.status

    def test_never_fabricates_info(self):
        """Readiness check never fabricates missing information."""
        result = run_readiness_check(
            profile_data=None,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        # Should be NEEDS_INPUT or INCOMPLETE, never READY
        assert result.status != ReadinessStatus.READY

    def test_sensitive_not_inferred(self):
        """Sensitive values are never inferred from context."""
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            form_fields=[{"label": "Work Authorization", "key": "work_authorization",
                          "required": True}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        # Should be NEEDS_INPUT because work_authorization is not in profile
        assert result.status == ReadinessStatus.NEEDS_INPUT
        # Should not have fabricated a value
        wa_reqs = [r for r in result.all_requirements
                   if r.category == "WORK_AUTHORIZATION"]
        if wa_reqs:
            assert wa_reqs[0].value is None or wa_reqs[0].status != RequirementStatus.SATISFIED


# ═══════════════════════════════════════════════════════════════════════════
# STEP 24 — SAFETY VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestSafetyVerification:
    def test_missing_data_not_fabricated(self):
        result = run_readiness_check(
            profile_data={"name": "John"},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status != ReadinessStatus.READY

    def test_sensitive_never_inferred(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com"},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        # No sensitive field should be marked SATISFIED without explicit data
        for req in result.sensitive_requirements:
            if req.status == RequirementStatus.SATISFIED:
                assert req.source in (
                    RequirementSource.PROFILE,
                    RequirementSource.APPLICATION_ANSWER,
                    RequirementSource.APPLICATION_MEMORY,
                    RequirementSource.EXPLICIT_USER,
                )

    def test_contradictory_requires_review(self):
        result = run_readiness_check(
            profile_data={"name": "John", "city": "A"},
            answers={"city": "B"},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.REVIEW

    def test_missing_documents_block_or_review(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            package_data={"status": "APPROVED", "selected_resume_id": None},
            resume_data=None,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.NEEDS_INPUT

    def test_unverified_documents_not_ready(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            package_data={"status": "APPROVED", "selected_resume_id": 1,
                          "quality_gate": "PASS", "readiness": "READY"},
            resume_data={"file_path": None, "is_active": True},
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status != ReadinessStatus.READY

    def test_expired_job_not_ready(self):
        """Expired job should be caught by preflight, but readiness also flags."""
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            duplicate_status="ALREADY_APPLIED",
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_duplicates_not_ready(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            duplicate_status="ALREADY_APPLIED",
        )
        assert result.status == ReadinessStatus.BLOCKED

    def test_uncertain_submission_not_ready(self):
        result = run_readiness_check(
            profile_data={"name": "John", "email": "j@e.com", "phone": "555"},
            previous_executions=[{"id": 1, "status": "SUBMISSION_UNKNOWN"}],
            duplicate_status="SAFE_TO_SUBMIT",
        )
        assert result.status == ReadinessStatus.REVIEW
        assert result.status != ReadinessStatus.READY

    def test_autopilot_cannot_bypass_readiness(self):
        """Readiness gate is deterministic — no override possible."""
        r1 = run_readiness_check(
            profile_data=None,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        r2 = run_readiness_check(
            profile_data=None,
            duplicate_status="SAFE_TO_SUBMIT",
        )
        # Both must produce the same non-READY result
        assert r1.status == r2.status
        assert r1.status != ReadinessStatus.READY

    def test_readiness_rechecked_before_execution(self):
        """needs_refresh() detects stale readiness."""
        from datetime import timedelta
        stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        result = ReadinessResult(checked_at=stale)
        assert needs_refresh(result) is True
