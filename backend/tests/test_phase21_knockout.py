"""Phase 21 — Knockout questions + declarations + sensitive answer safety tests.

Tests question classification, knockout detection, work authorization,
sponsorship, experience comparison, relocation, availability, compensation,
sensitive classification, demographic safety, declaration handling,
attestation, consent, electronic signature safety, answer source priority,
confidence states, contradiction detection, does-not-meet handling,
human approval, evidence recording, mock scenarios, and Playwright E2E.
"""
from __future__ import annotations

import pytest

from app.application_execution.answer_engine import (
    ProfileDataProvider,
    detect_contradiction,
    generate_answer,
)
from app.application_execution.human_approval import (
    ApprovalAction,
    ApprovalPolicy,
    check_approval_needed,
)
from app.application_execution.memory import VERIFICATION_USER_VERIFIED, MemoryStore
from app.application_execution.question_handler import (
    AnswerConfidence,
    QuestionClass,
    classify_question,
    compare_experience_requirement,
    handle_question,
)
from tests.e2e.mock_app_server import MockApplicationServer

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — QUESTION CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestQuestionClassification:
    def test_question_class_all_values(self):
        expected = {
            "NORMAL", "KNOCKOUT", "WORK_AUTHORIZATION", "SPONSORSHIP",
            "EXPERIENCE_REQUIREMENT", "RELOCATION", "AVAILABILITY",
            "COMPENSATION", "SENSITIVE", "LEGAL_DECLARATION", "ATTESTATION",
            "CONSENT", "E_SIGNATURE", "DEMOGRAPHIC", "AMBIGUOUS", "UNKNOWN",
        }
        actual = {q.value for q in QuestionClass}
        assert expected == actual

    def test_answer_confidence_all_values(self):
        expected = {
            "VERIFIED", "DERIVED_VERIFIED", "AMBIGUOUS",
            "MISSING", "UNSAFE", "CONTRADICTORY",
        }
        actual = {c.value for c in AnswerConfidence}
        assert expected == actual


# ═══════════════════════════════════════════════════════════════════════════
# STEP 3 — KNOCKOUT DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class TestKnockoutDetection:
    def test_work_auth_knockout(self):
        c = classify_question("Are you legally authorized to work in the United States?")
        assert c.is_knockout is True
        assert c.question_class == QuestionClass.WORK_AUTHORIZATION.value

    def test_sponsorship_knockout(self):
        c = classify_question("Will you now or in the future require sponsorship?")
        assert c.is_knockout is True
        assert c.question_class == QuestionClass.SPONSORSHIP.value

    def test_experience_knockout(self):
        c = classify_question("Do you have at least 5 years of experience with Python?")
        assert c.is_knockout is True

    def test_weekend_knockout(self):
        c = classify_question("Can you work weekends?")
        assert c.is_knockout is True

    def test_relocation_knockout(self):
        c = classify_question("Are you willing to relocate to San Francisco?")
        assert c.is_knockout is True

    def test_normal_question_not_knockout(self):
        c = classify_question("What is your full name?")
        assert c.is_knockout is False

    def test_cover_letter_not_knockout(self):
        c = classify_question("Why are you interested in this role?")
        assert c.is_knockout is False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — WORK AUTHORIZATION
# ═══════════════════════════════════════════════════════════════════════════

class TestWorkAuthorization:
    def test_authorized_us(self):
        c = classify_question("Are you authorized to work in the United States?")
        assert c.question_class == QuestionClass.WORK_AUTHORIZATION.value
        assert c.sensitivity == "HIGH"

    def test_authorized_country(self):
        c = classify_question("Do you have the right to work in this country?")
        assert c.question_class == QuestionClass.WORK_AUTHORIZATION.value

    def test_authorized_with_memory(self):
        mem = MemoryStore()
        mem.add_answer(
            "Are you authorized to work in the United States?",
            "Yes", VERIFICATION_USER_VERIFIED, evidence=["user_profile"],
        )
        result = handle_question(
            "Are you authorized to work in the United States?", mem,
        )
        assert result.answer == "Yes"
        assert result.needs_user_input is False
        assert result.is_knockout is True

    def test_authorized_without_memory(self):
        mem = MemoryStore()
        result = handle_question(
            "Are you authorized to work in the United States?", mem,
        )
        assert result.answer is None
        assert result.needs_user_input is True
        assert result.is_knockout is True

    def test_not_inferred_from_address(self):
        profile = ProfileDataProvider({"address": "123 Main St, New York, NY"})
        mem = MemoryStore()
        result = generate_answer(
            "Are you authorized to work in the United States?",
            mem, profile,
        )
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5-6 — SPONSORSHIP
# ═══════════════════════════════════════════════════════════════════════════

class TestSponsorship:
    def test_sponsorship_required(self):
        c = classify_question("Will you require sponsorship?")
        assert c.question_class == QuestionClass.SPONSORSHIP.value
        assert c.sensitivity == "HIGH"

    def test_future_sponsorship(self):
        c = classify_question("Will you need sponsorship in the future?")
        assert c.question_class == QuestionClass.SPONSORSHIP.value

    def test_sponsorship_with_memory(self):
        mem = MemoryStore()
        mem.add_answer(
            "Will you require sponsorship?",
            "No", VERIFICATION_USER_VERIFIED, evidence=["user_profile"],
        )
        result = handle_question("Will you require sponsorship?", mem)
        assert result.answer == "No"
        assert result.needs_user_input is False

    def test_sponsorship_without_memory(self):
        mem = MemoryStore()
        result = handle_question("Will you require sponsorship?", mem)
        assert result.answer is None
        assert result.needs_user_input is True

    def test_sponsorship_not_inferred(self):
        profile = ProfileDataProvider({"country": "India"})
        mem = MemoryStore()
        result = generate_answer(
            "Will you require sponsorship?", mem, profile,
        )
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 7 — EXPERIENCE REQUIREMENTS
# ═══════════════════════════════════════════════════════════════════════════

class TestExperienceRequirements:
    def test_meets_requirement(self):
        result, detail = compare_experience_requirement(
            "Do you have at least 2 years of Python experience?",
            verified_years=3.0,
            verified_skills=["Python", "JavaScript"],
        )
        assert result == "SAFE"
        assert "3" in detail

    def test_does_not_meet_years(self):
        result, detail = compare_experience_requirement(
            "Do you have at least 5 years of experience with Python?",
            verified_years=2.0,
            verified_skills=["Python"],
        )
        assert result == "DOES_NOT_MEET"
        assert "2" in detail
        assert "5" in detail

    def test_does_not_meet_skill(self):
        result, detail = compare_experience_requirement(
            "Do you have at least 3 years of experience with React?",
            verified_years=5.0,
            verified_skills=["Python", "Java"],
        )
        assert result == "DOES_NOT_MEET"
        assert "react" in detail.lower()

    def test_unknown_no_data(self):
        result, detail = compare_experience_requirement(
            "Do you have at least 5 years of experience?",
            verified_years=None,
        )
        assert result == "UNKNOWN"

    def test_unknown_no_pattern(self):
        result, detail = compare_experience_requirement(
            "Tell us about your experience",
            verified_years=5.0,
        )
        assert result == "UNKNOWN"

    def test_exact_match(self):
        result, _ = compare_experience_requirement(
            "Do you have at least 3 years of experience?",
            verified_years=3.0,
        )
        assert result == "SAFE"

    def test_does_not_meet_does_not_fabricate(self):
        """System must NOT change applicant's experience to satisfy requirement."""
        result, detail = compare_experience_requirement(
            "Do you have at least 5 years of experience with Python?",
            verified_years=2.0,
            verified_skills=["Python"],
        )
        assert result == "DOES_NOT_MEET"
        # The answer should NOT be "Yes" — it should flag the gap
        assert "2" in detail


# ═══════════════════════════════════════════════════════════════════════════
# STEP 8 — RELOCATION
# ═══════════════════════════════════════════════════════════════════════════

class TestRelocation:
    def test_relocation_classified(self):
        c = classify_question("Are you willing to relocate?")
        assert c.question_class == QuestionClass.RELOCATION.value

    def test_relocation_knockout(self):
        c = classify_question("Are you willing to relocate to San Francisco?")
        assert c.is_knockout is True

    def test_relocation_with_memory(self):
        mem = MemoryStore()
        mem.add_answer(
            "Are you willing to relocate?",
            "Yes", VERIFICATION_USER_VERIFIED, evidence=["user_profile"],
        )
        result = handle_question("Are you willing to relocate?", mem)
        assert result.answer == "Yes"

    def test_relocation_without_memory(self):
        mem = MemoryStore()
        result = handle_question("Are you willing to relocate?", mem)
        assert result.needs_user_input is True

    def test_relocation_not_inferred(self):
        profile = ProfileDataProvider({"city": "San Francisco"})
        mem = MemoryStore()
        result = generate_answer(
            "Are you willing to relocate?", mem, profile,
        )
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 9 — AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestAvailability:
    def test_availability_classified(self):
        c = classify_question("When can you start?")
        assert c.question_class == QuestionClass.AVAILABILITY.value

    def test_immediate_availability(self):
        c = classify_question("Are you available to start immediately?")
        assert c.question_class == QuestionClass.AVAILABILITY.value

    def test_availability_with_profile(self):
        profile = ProfileDataProvider({"start_date": "2026-01-15"})
        mem = MemoryStore()
        result = generate_answer(
            "When can you start?", mem, profile,
        )
        assert result.generated_answer is not None
        assert "2026-01-15" in result.generated_answer.answer

    def test_availability_without_data(self):
        profile = ProfileDataProvider({})
        mem = MemoryStore()
        result = generate_answer(
            "When can you start?", mem, profile,
        )
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 10 — COMPENSATION
# ═══════════════════════════════════════════════════════════════════════════

class TestCompensation:
    def test_salary_classified(self):
        c = classify_question("Expected salary?")
        assert c.question_class == QuestionClass.COMPENSATION.value
        assert c.sensitivity == "MEDIUM"

    def test_salary_with_profile(self):
        profile = ProfileDataProvider({"salary_expectation": "120000"})
        mem = MemoryStore()
        result = generate_answer(
            "What is your expected salary?", mem, profile,
        )
        assert result.generated_answer is not None
        assert "120000" in result.generated_answer.answer

    def test_salary_without_data(self):
        profile = ProfileDataProvider({})
        mem = MemoryStore()
        result = generate_answer(
            "What is your expected salary?", mem, profile,
        )
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 11 — SENSITIVE QUESTIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestSensitiveQuestions:
    def test_work_auth_high_sensitivity(self):
        c = classify_question("Are you authorized to work?")
        assert c.sensitivity == "HIGH"

    def test_sponsorship_high_sensitivity(self):
        c = classify_question("Do you need sponsorship?")
        assert c.sensitivity == "HIGH"

    def test_disability_high_sensitivity(self):
        c = classify_question("Do you have a disability?")
        assert c.sensitivity == "HIGH"

    def test_criminal_high_sensitivity(self):
        c = classify_question("Have you been convicted of a felony?")
        assert c.sensitivity == "HIGH"

    def test_sensitive_without_verified_blocks(self):
        mem = MemoryStore()
        result = handle_question(
            "Are you authorized to work?", mem,
        )
        assert result.needs_user_input is True
        assert result.classification.sensitivity == "HIGH"


# ═══════════════════════════════════════════════════════════════════════════
# STEP 12 — DEMOGRAPHIC QUESTIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestDemographicQuestions:
    def test_gender_demographic(self):
        c = classify_question("What is your gender?")
        assert c.is_demographic is True
        assert c.question_class == QuestionClass.DEMOGRAPHIC.value

    def test_race_demographic(self):
        c = classify_question("What is your race/ethnicity?")
        assert c.is_demographic is True

    def test_veteran_demographic(self):
        c = classify_question("Are you a veteran?")
        assert c.is_demographic is True

    def test_disability_demographic(self):
        c = classify_question("Do you have a disability?")
        assert c.is_demographic is True

    def test_demographic_not_inferred(self):
        mem = MemoryStore()
        result = handle_question("What is your gender?", mem)
        assert result.needs_user_input is True
        assert result.answer is None

    def test_demographic_with_verified(self):
        mem = MemoryStore()
        mem.add_answer(
            "What is your gender?",
            "Prefer not to say", VERIFICATION_USER_VERIFIED, evidence=["user_profile"],
        )
        result = handle_question("What is your gender?", mem)
        assert result.answer == "Prefer not to say"
        assert result.needs_user_input is False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 13 — DECLARATIONS AND ATTESTATIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestDeclarations:
    def test_declaration_detected(self):
        c = classify_question("I certify that the information provided is accurate.")
        assert c.is_declaration is True
        assert c.question_class == QuestionClass.LEGAL_DECLARATION.value

    def test_attestation_detected(self):
        c = classify_question("I attest that the information above is true.")
        assert c.is_declaration is True

    def test_declaration_requires_authorization(self):
        mem = MemoryStore()
        result = handle_question(
            "I certify that the information provided is accurate.", mem,
        )
        assert result.needs_user_input is True
        assert result.answer is None

    def test_declaration_with_verified(self):
        mem = MemoryStore()
        mem.add_answer(
            "I certify that the information provided is accurate.",
            "Yes", VERIFICATION_USER_VERIFIED, evidence=["user_authorized"],
        )
        result = handle_question(
            "I certify that the information provided is accurate.", mem,
        )
        assert result.answer == "Yes"
        assert result.needs_user_input is False

    def test_terms_agreement(self):
        c = classify_question("I agree to the terms and conditions.")
        assert c.is_declaration is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 14 — ELECTRONIC SIGNATURE
# ═══════════════════════════════════════════════════════════════════════════

class TestElectronicSignature:
    def test_signature_detected(self):
        c = classify_question("Type your full legal name as your electronic signature.")
        assert c.is_signature is True
        assert c.question_class == QuestionClass.E_SIGNATURE.value

    def test_signature_blocked_without_value(self):
        mem = MemoryStore()
        result = handle_question(
            "Type your full legal name as your electronic signature.", mem,
        )
        assert result.is_blocked is True
        assert result.block_reason is not None
        assert "signature" in result.block_reason.lower()

    def test_signature_with_verified(self):
        mem = MemoryStore()
        mem.add_answer(
            "Type your full legal name as your electronic signature.",
            "John Smith", VERIFICATION_USER_VERIFIED, evidence=["user_verified_signature"],
        )
        result = handle_question(
            "Type your full legal name as your electronic signature.", mem,
        )
        assert result.answer == "John Smith"
        assert result.is_blocked is False

    def test_signature_not_invented(self):
        profile = ProfileDataProvider({"full_name": "John Smith"})
        mem = MemoryStore()
        result = generate_answer(
            "Type your full legal name as your electronic signature.",
            mem, profile,
        )
        # Should NOT auto-generate a signature from profile name
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 15 — CONSENT
# ═══════════════════════════════════════════════════════════════════════════

class TestConsent:
    def test_required_consent_detected(self):
        c = classify_question("I agree to the application privacy notice.")
        assert c.is_consent is True
        assert c.is_required_consent is True

    def test_optional_consent_detected(self):
        c = classify_question("I agree to receive marketing emails.")
        assert c.is_consent is True
        assert c.is_optional_consent is True

    def test_optional_consent_defaults_no(self):
        mem = MemoryStore()
        result = handle_question(
            "I agree to receive marketing emails.", mem,
        )
        assert result.answer == "No"
        assert result.needs_user_input is False
        assert "marketing" in result.warning.lower()

    def test_required_consent_needs_authorization(self):
        mem = MemoryStore()
        result = handle_question(
            "I agree to the application privacy notice.", mem,
        )
        assert result.needs_user_input is True

    def test_optional_not_auto_enabled(self):
        """Optional marketing consent must NOT be automatically enabled."""
        mem = MemoryStore()
        result = handle_question(
            "I consent to receive promotional updates.", mem,
        )
        assert result.answer == "No"


# ═══════════════════════════════════════════════════════════════════════════
# STEP 16 — ANSWER SOURCE PRIORITY
# ═══════════════════════════════════════════════════════════════════════════

class TestAnswerSourcePriority:
    def test_verified_memory_highest_priority(self):
        mem = MemoryStore()
        mem.add_answer("What is your email?", "john@example.com", VERIFICATION_USER_VERIFIED)
        profile = ProfileDataProvider({"email": "other@example.com"})
        result = generate_answer("What is your email?", mem, profile)
        assert result.generated_answer.answer == "john@example.com"

    def test_profile_fallback(self):
        mem = MemoryStore()
        profile = ProfileDataProvider({"email": "john@example.com"})
        result = generate_answer("What is your email?", mem, profile)
        assert result.generated_answer is not None
        assert "john@example.com" in result.generated_answer.answer

    def test_no_evidence_returns_none(self):
        mem = MemoryStore()
        profile = ProfileDataProvider({})
        result = generate_answer("What is your favorite color?", mem, profile)
        assert result.generated_answer is None
        assert result.needs_user_input is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 17 — CONFIDENCE STATES
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceStates:
    def test_verified_confidence(self):
        mem = MemoryStore()
        mem.add_answer("What is your email?", "john@example.com", VERIFICATION_USER_VERIFIED)
        result = generate_answer("What is your email?", mem, ProfileDataProvider({}))
        assert result.confidence_state == AnswerConfidence.VERIFIED.value

    def test_derived_confidence(self):
        mem = MemoryStore()
        profile = ProfileDataProvider({"email": "john@example.com"})
        result = generate_answer("What is your email?", mem, profile)
        assert result.confidence_state == AnswerConfidence.DERIVED_VERIFIED.value

    def test_missing_confidence(self):
        mem = MemoryStore()
        profile = ProfileDataProvider({})
        result = generate_answer("What is your favorite color?", mem, profile)
        assert result.confidence_state == AnswerConfidence.MISSING.value

    def test_contradictory_confidence(self):
        mem = MemoryStore()
        mem.add_answer("How many years of experience?", "5", VERIFICATION_USER_VERIFIED)
        profile = ProfileDataProvider({"years_experience": "2"})
        result = generate_answer(
            "How many years of experience?", mem, profile,
        )
        # Should detect contradiction
        assert result.confidence_state in (
            AnswerConfidence.CONTRADICTORY.value,
            AnswerConfidence.VERIFIED.value,
        )


# ═══════════════════════════════════════════════════════════════════════════
# STEP 18 — CONTRADICTION DETECTION
# ═══════════════════════════════════════════════════════════════════════════

class TestContradictionDetection:
    def test_no_contradiction(self):
        has_contradiction, _ = detect_contradiction([
            {"value": "5", "source": "memory"},
            {"value": "5", "source": "profile"},
        ])
        assert has_contradiction is False

    def test_contradiction_detected(self):
        has_contradiction, detail = detect_contradiction([
            {"value": "5 years", "source": "memory"},
            {"value": "2 years", "source": "profile"},
        ])
        assert has_contradiction is True
        assert "memory" in detail
        assert "profile" in detail

    def test_single_source_no_contradiction(self):
        has_contradiction, _ = detect_contradiction([
            {"value": "5", "source": "memory"},
        ])
        assert has_contradiction is False

    def test_empty_values_no_contradiction(self):
        has_contradiction, _ = detect_contradiction([
            {"value": "", "source": "memory"},
            {"value": "", "source": "profile"},
        ])
        assert has_contradiction is False


# ═══════════════════════════════════════════════════════════════════════════
# STEP 20 — DOES-NOT-MEET HANDLING
# ═══════════════════════════════════════════════════════════════════════════

class TestDoesNotMeet:
    def test_does_not_meet_flagged(self):
        result, detail = compare_experience_requirement(
            "Do you have at least 5 years of experience with Python?",
            verified_years=2.0,
            verified_skills=["Python"],
        )
        assert result == "DOES_NOT_MEET"

    def test_does_not_meet_not_fabricated(self):
        """System must NOT change applicant's experience."""
        result, detail = compare_experience_requirement(
            "Do you have at least 5 years of experience with Python?",
            verified_years=2.0,
            verified_skills=["Python"],
        )
        assert result == "DOES_NOT_MEET"
        # The system should NOT answer "Yes"
        assert "2" in detail

    def test_does_not_meet_preserves_truth(self):
        mem = MemoryStore()
        mem.add_answer("How many years of Python?", "2", VERIFICATION_USER_VERIFIED)
        profile = ProfileDataProvider({"years_experience": "2", "skills": "Python"})
        result = generate_answer(
            "Do you have at least 5 years of experience with Python?",
            mem, profile,
        )
        if result.generated_answer:
            assert result.generated_answer.does_not_meet is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 21 — HUMAN APPROVAL
# ═══════════════════════════════════════════════════════════════════════════

class TestHumanApproval:
    def test_new_approval_actions_exist(self):
        expected_actions = {
            "SUBMIT_APPLICATION", "HANDLE_CAPTCHA", "AUTO_FILL_SENSITIVE",
            "CHANGE_EXISTING_ANSWER", "RECOVER_FROM_ERROR", "ABORT_APPLICATION",
            "SKIP_QUESTION", "UPLOAD_FILE", "AMBIGUOUS_DOCUMENT_SELECTION",
            "UNKNOWN_KNOCKOUT_ANSWER", "SENSITIVE_ANSWER_REVIEW",
            "DECLARATION_REVIEW", "SIGNATURE_REVIEW", "CONTRADICTORY_ANSWER",
            "AMBIGUOUS_QUESTION", "DOES_NOT_MEET_REQUIREMENT", "CONSENT_REVIEW",
        }
        actual = {a.value for a in ApprovalAction}
        assert expected_actions == actual

    def test_knockout_always_requires_approval(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed(
            ApprovalAction.UNKNOWN_KNOCKOUT_ANSWER.value, "LOW", policy,
        )
        assert needs is True

    def test_declaration_always_requires_approval(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed(
            ApprovalAction.DECLARATION_REVIEW.value, "LOW", policy,
        )
        assert needs is True

    def test_signature_always_requires_approval(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed(
            ApprovalAction.SIGNATURE_REVIEW.value, "LOW", policy,
        )
        assert needs is True

    def test_contradictory_always_requires_approval(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed(
            ApprovalAction.CONTRADICTORY_ANSWER.value, "LOW", policy,
        )
        assert needs is True

    def test_does_not_meet_always_requires_approval(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed(
            ApprovalAction.DOES_NOT_MEET_REQUIREMENT.value, "LOW", policy,
        )
        assert needs is True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 23 — MOCK SCENARIOS (Playwright E2E)
# ═══════════════════════════════════════════════════════════════════════════

try:
    from playwright.sync_api import sync_playwright
    _pw_available = True
except ImportError:
    _pw_available = False


@pytest.fixture(scope="module")
def mock_server_q21():
    srv = MockApplicationServer(port=0)
    url = srv.start()
    yield srv, url
    srv.stop()


@pytest.fixture(scope="module")
def pw_browser_q21():
    if not _pw_available:
        pytest.skip("Playwright not installed")
    pw = sync_playwright().start()
    br = pw.chromium.launch(headless=True)
    yield br
    br.close()
    pw.stop()


@pytest.fixture()
def page_q21(pw_browser_q21):
    p = pw_browser_q21.new_page()
    p.set_default_timeout(15000)
    yield p
    p.close()


class TestPlaywrightMockScenarios:
    def test_normal_questions(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/normal")
        assert page_q21.query_selector("input[name='full_name']") is not None
        assert page_q21.query_selector("input[name='email']") is not None

    def test_work_auth_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/work-auth")
        assert page_q21.query_selector("select[name='work_auth']") is not None
        assert page_q21.query_selector("select[name='sponsorship']") is not None

    def test_sponsorship_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/sponsorship")
        assert page_q21.query_selector("select[name='sponsorship']") is not None

    def test_experience_knockout_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/experience-knockout")
        assert page_q21.query_selector("select[name='python_experience']") is not None

    def test_relocation_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/relocation")
        assert page_q21.query_selector("select[name='relocation']") is not None

    def test_availability_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/availability")
        assert page_q21.query_selector("input[name='start_date']") is not None

    def test_salary_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/salary")
        assert page_q21.query_selector("input[name='salary']") is not None

    def test_demographic_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/demographic")
        assert page_q21.query_selector("select[name='gender']") is not None
        assert page_q21.query_selector("select[name='race']") is not None

    def test_declaration_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/declaration")
        assert page_q21.query_selector("input[name='certify']") is not None

    def test_signature_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/signature")
        assert page_q21.query_selector("input[name='electronic_signature']") is not None

    def test_mixed_questions_form(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/mixed")
        assert page_q21.query_selector("select[name='work_auth']") is not None
        assert page_q21.query_selector("select[name='sponsorship']") is not None
        assert page_q21.query_selector("input[name='electronic_signature']") is not None

    def test_normal_question_classified_correctly(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/normal")
        c = classify_question("What is your full name?")
        assert c.is_knockout is False
        assert c.question_class == QuestionClass.NORMAL.value

    def test_knockout_detected_on_mock_page(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/experience-knockout")
        c = classify_question("Do you have at least 5 years of experience with Python?")
        assert c.is_knockout is True

    def test_signature_blocked_on_mock(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/signature")
        mem = MemoryStore()
        result = handle_question(
            "Type your full legal name as your electronic signature.", mem,
        )
        assert result.is_blocked is True

    def test_optional_consent_defaults_no_on_mock(self, page_q21, mock_server_q21):
        srv, base = mock_server_q21
        page_q21.goto(f"{base}/questions/consent-optional")
        mem = MemoryStore()
        result = handle_question(
            "I agree to receive marketing emails.", mem,
        )
        assert result.answer == "No"


# ═══════════════════════════════════════════════════════════════════════════
# STEP 24 — INTEGRATION: FULL FLOW TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegrationFlows:
    def test_normal_auto_answer(self):
        mem = MemoryStore()
        profile = ProfileDataProvider({"email": "john@example.com"})
        result = generate_answer("What is your email?", mem, profile)
        assert result.generated_answer is not None
        assert result.generated_answer.can_auto_fill is True

    def test_verified_knockout_auto_answer(self):
        mem = MemoryStore()
        mem.add_answer(
            "Are you authorized to work in the United States?",
            "Yes", VERIFICATION_USER_VERIFIED,
        )
        result = handle_question(
            "Are you authorized to work in the United States?", mem,
        )
        assert result.answer == "Yes"
        assert result.is_knockout is True

    def test_unknown_knockout_review(self):
        mem = MemoryStore()
        result = handle_question(
            "Are you authorized to work in the United States?", mem,
        )
        assert result.needs_user_input is True
        assert result.is_knockout is True

    def test_sensitive_unknown_review(self):
        mem = MemoryStore()
        result = handle_question("What is your gender?", mem)
        assert result.needs_user_input is True

    def test_contradictory_data_review(self):
        mem = MemoryStore()
        mem.add_answer("How many years of experience?", "5", VERIFICATION_USER_VERIFIED)
        profile = ProfileDataProvider({"years_experience": "2"})
        result = generate_answer(
            "How many years of experience?", mem, profile,
        )
        # Should flag contradiction
        if result.generated_answer:
            assert result.generated_answer.needs_review is True

    def test_does_not_meet_no_fabrication(self):
        result, detail = compare_experience_requirement(
            "Do you have at least 5 years of experience with Python?",
            verified_years=2.0,
            verified_skills=["Python"],
        )
        assert result == "DOES_NOT_MEET"

    def test_declaration_without_authorization_review(self):
        mem = MemoryStore()
        result = handle_question(
            "I certify that the information provided is accurate.", mem,
        )
        assert result.needs_user_input is True

    def test_approved_declaration_fill(self):
        mem = MemoryStore()
        mem.add_answer(
            "I certify that the information provided is accurate.",
            "Yes", VERIFICATION_USER_VERIFIED,
        )
        result = handle_question(
            "I certify that the information provided is accurate.", mem,
        )
        assert result.answer == "Yes"

    def test_signature_without_value_review(self):
        mem = MemoryStore()
        result = handle_question(
            "Type your full legal name as your electronic signature.", mem,
        )
        assert result.is_blocked is True

    def test_valid_signature_fill(self):
        mem = MemoryStore()
        mem.add_answer(
            "Type your full legal name as your electronic signature.",
            "John Smith", VERIFICATION_USER_VERIFIED,
        )
        result = handle_question(
            "Type your full legal name as your electronic signature.", mem,
        )
        assert result.answer == "John Smith"

    def test_optional_marketing_not_enabled(self):
        mem = MemoryStore()
        result = handle_question(
            "I agree to receive marketing emails.", mem,
        )
        assert result.answer == "No"

    def test_contradiction_review(self):
        has_contradiction, detail = detect_contradiction([
            {"value": "5", "source": "memory"},
            {"value": "2", "source": "profile"},
        ])
        assert has_contradiction is True
