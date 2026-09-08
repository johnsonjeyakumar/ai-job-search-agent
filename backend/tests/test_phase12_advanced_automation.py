"""Tests for Phase 12: Advanced Application Automation Engine."""
from __future__ import annotations

from app.application_execution.analytics import AnalyticsStore
from app.application_execution.base import DetectedField
from app.application_execution.checkpoint import (
    Checkpoint,
    CheckpointStore,
    CheckpointType,
    create_form_inspected_checkpoint,
)
from app.application_execution.field_catalog import (
    ALL_FIELD_CONCEPTS,
    CATEGORY_PERSONAL,
    CATEGORY_WORK,
    CONCEPT_BY_CANONICAL,
    SENSITIVITY_HIGH,
    SENSITIVITY_LOW,
    SENSITIVITY_MEDIUM,
    get_category,
    get_sensitivity,
    lookup_concept,
)
from app.application_execution.human_approval import (
    ApprovalPolicy,
    ApprovalStatus,
    ApprovalStore,
    check_approval_needed,
)
from app.application_execution.memory import (
    VERIFICATION_USER_VERIFIED,
    MemoryStore,
)
from app.application_execution.pipeline import (
    PipelineField,
    detect_contradictions,
    run_pipeline,
)
from app.application_execution.question_handler import (
    QUESTION_CATEGORY_AUTHORIZATION,
    QUESTION_CATEGORY_UNKNOWN,
    classify_question,
    handle_question,
)
from app.application_execution.security import (
    FIELD_CLASSIFICATION,
    SecurityController,
    validate_email,
    validate_phone,
    validate_url,
)
from app.application_execution.semantic_mapper import (
    CONFIDENCE_HIGH,
    CONFIDENCE_UNKNOWN,
    MAPPING_ALIAS,
    MAPPING_DETERMINISTIC,
    MAPPING_SEMANTIC,
    FieldMapping,
    map_field_semantic,
    map_fields_semantic,
)

# ---------------------------------------------------------------------------
# Field Catalog Tests
# ---------------------------------------------------------------------------

class TestFieldCatalog:
    """Tests for the field catalog."""

    def test_catalog_not_empty(self):
        assert len(ALL_FIELD_CONCEPTS) > 0

    def test_lookup_exact_alias(self):
        concept = lookup_concept("first name")
        assert concept is not None
        assert concept.canonical == "FIRST_NAME"

    def test_lookup_case_insensitive(self):
        concept = lookup_concept("Email Address")
        assert concept is not None
        assert concept.canonical == "EMAIL"

    def test_lookup_not_found(self):
        concept = lookup_concept("xyz_nonexistent")
        assert concept is None

    def test_sensitivity_levels(self):
        assert get_sensitivity("FIRST_NAME") == SENSITIVITY_LOW
        assert get_sensitivity("SALARY_EXPECTATION") == SENSITIVITY_MEDIUM
        assert get_sensitivity("WORK_AUTHORIZATION") == SENSITIVITY_HIGH

    def test_categories(self):
        assert get_category("FIRST_NAME") == CATEGORY_PERSONAL
        assert get_category("CURRENT_COMPANY") == CATEGORY_WORK

    def test_all_canonicals_indexed(self):
        for concept in ALL_FIELD_CONCEPTS:
            assert concept.canonical in CONCEPT_BY_CANONICAL


# ---------------------------------------------------------------------------
# Semantic Mapper Tests
# ---------------------------------------------------------------------------

class TestSemanticMapper:
    """Tests for semantic field mapping."""

    def test_exact_label_match(self):
        field = DetectedField(label="first name", kind="text")
        mapping = map_field_semantic(field)
        assert mapping.canonical == "FIRST_NAME"
        assert mapping.confidence == CONFIDENCE_HIGH
        assert mapping.mapping_method in (MAPPING_ALIAS, MAPPING_DETERMINISTIC)

    def test_alias_match(self):
        field = DetectedField(label="email address", kind="text")
        mapping = map_field_semantic(field)
        assert mapping.canonical == "EMAIL"
        assert mapping.confidence == CONFIDENCE_HIGH

    def test_semantic_match(self):
        field = DetectedField(label="what is your current employer", kind="text")
        mapping = map_field_semantic(field)
        assert mapping.canonical is not None
        assert mapping.mapping_method in (MAPPING_ALIAS, MAPPING_SEMANTIC)

    def test_no_match(self):
        field = DetectedField(label="favorite color", kind="text")
        mapping = map_field_semantic(field)
        assert mapping.canonical is None
        assert mapping.confidence == CONFIDENCE_UNKNOWN

    def test_user_verified_mapping(self):
        field = DetectedField(label="custom field", kind="text")
        user_verified = {"custom field": "EMAIL"}
        mapping = map_field_semantic(field, user_verified)
        assert mapping.canonical == "EMAIL"
        assert mapping.mapping_method == "USER_VERIFIED"

    def test_sensitivity_detection(self):
        field = DetectedField(label="visa sponsorship", kind="select")
        mapping = map_field_semantic(field)
        assert mapping.sensitivity == SENSITIVITY_HIGH

    def test_map_multiple_fields(self):
        detected = [
            DetectedField(label="first name", kind="text"),
            DetectedField(label="email", kind="text"),
            DetectedField(label="phone number", kind="text"),
        ]
        result = map_fields_semantic(detected)
        assert result.mapped_count == 3
        assert result.high_confidence_count == 3


# ---------------------------------------------------------------------------
# Memory Tests
# ---------------------------------------------------------------------------

class TestMemory:
    """Tests for application memory."""

    def test_add_answer(self):
        store = MemoryStore()
        answer = store.add_answer("What is your email?", "test@example.com")
        assert answer.answer == "test@example.com"
        assert answer.verification_status == VERIFICATION_USER_VERIFIED

    def test_get_answer(self):
        store = MemoryStore()
        store.add_answer("What is your email?", "test@example.com")
        answer = store.get_answer("What is your email?")
        assert answer is not None
        assert answer.answer == "test@example.com"
        assert answer.use_count == 1

    def test_get_verified_answer(self):
        store = MemoryStore()
        store.add_answer("Are you authorized?", "Yes", source=VERIFICATION_USER_VERIFIED)
        answer = store.get_verified_answer("Are you authorized?")
        assert answer is not None

    def test_revoke_answer(self):
        store = MemoryStore()
        store.add_answer("What is your email?", "test@example.com")
        assert store.revoke_answer("What is your email?") is True
        # Revoked answers are no longer returned by get_answer()
        answer = store.get_answer("What is your email?")
        assert answer is None
        # But the internal state is still EXPIRED
        from app.application_execution.memory import _norm
        internal = store.answers.get(_norm("What is your email?"))
        assert internal.verification_status == "EXPIRED"

    def test_list_answers(self):
        store = MemoryStore()
        store.add_answer("What is your email?", "test@example.com")
        store.add_answer("What is your phone?", "1234567890")
        answers = store.list_answers()
        assert len(answers) == 2

    def test_unknown_question(self):
        store = MemoryStore()
        unknown = store.add_unknown_question(
            "What is your favorite framework?",
            options=["React", "Vue", "Angular"],
        )
        assert unknown.raw_question == "What is your favorite framework?"
        assert len(unknown.available_options) == 3


# ---------------------------------------------------------------------------
# Question Handler Tests
# ---------------------------------------------------------------------------

class TestQuestionHandler:
    """Tests for question handling."""

    def test_classify_authorization(self):
        classification = classify_question("Are you authorized to work?")
        assert classification.category == QUESTION_CATEGORY_AUTHORIZATION
        assert classification.sensitivity == "HIGH"
        assert classification.is_known_concept is True

    def test_classify_unknown(self):
        classification = classify_question("What is your favorite dessert?")
        assert classification.category == QUESTION_CATEGORY_UNKNOWN

    def test_handle_with_verified_answer(self):
        store = MemoryStore()
        store.add_answer("Are you authorized?", "Yes")
        result = handle_question("Are you authorized?", store)
        assert result.answer == "Yes"
        assert result.needs_user_input is False

    def test_handle_sensitive_without_verified(self):
        store = MemoryStore()
        result = handle_question("Are you authorized to work?", store)
        assert result.needs_user_input is True
        assert result.classification.sensitivity == "HIGH"

    def test_detect_boolean_options(self):
        classification = classify_question(
            "Will you require sponsorship?",
            available_options=["Yes", "No"],
        )
        from app.application_execution.question_handler import ANSWER_TYPE_BOOLEAN
        assert classification.answer_type == ANSWER_TYPE_BOOLEAN


# ---------------------------------------------------------------------------
# Answer Engine Regression Tests (Phase 12.1)
# ---------------------------------------------------------------------------

class TestAnswerEngine:
    """Regression tests for answer_engine.generate_answer()."""

    def test_no_type_error(self):
        """generate_answer must not raise TypeError."""
        from app.application_execution.answer_engine import ProfileDataProvider, generate_answer
        from app.application_execution.memory import MemoryStore

        result = generate_answer(
            "What is your email?",
            MemoryStore(),
            ProfileDataProvider({}),
        )
        assert result is not None
        assert hasattr(result, "question")
        assert hasattr(result, "generated_answer")

    def test_verified_memory_answer(self):
        """Verified memory answer is returned directly."""
        from app.application_execution.answer_engine import ProfileDataProvider, generate_answer
        from app.application_execution.memory import MemoryStore

        mem = MemoryStore()
        mem.add_answer("Are you authorized?", "Yes")
        result = generate_answer("Are you authorized?", mem, ProfileDataProvider({}))
        assert result.generated_answer is not None
        assert result.generated_answer.answer == "Yes"
        assert result.generated_answer.evidence_level == "EXACT"

    def test_profile_backed_answer(self):
        """Profile field match returns correct value."""
        from app.application_execution.answer_engine import ProfileDataProvider, generate_answer
        from app.application_execution.memory import MemoryStore

        profile = ProfileDataProvider({"email": "john@example.com"})
        result = generate_answer("What is your email?", MemoryStore(), profile)
        assert result.generated_answer is not None
        assert result.generated_answer.answer == "john@example.com"

    def test_unknown_question_needs_input(self):
        """Unknown question without profile match needs user input."""
        from app.application_execution.answer_engine import ProfileDataProvider, generate_answer
        from app.application_execution.memory import MemoryStore

        result = generate_answer(
            "What is your favorite color?",
            MemoryStore(),
            ProfileDataProvider({}),
        )
        assert result.needs_user_input is True
        assert result.generated_answer is None

    def test_sensitive_without_verified_needs_input(self):
        """Sensitive question without verified evidence needs user input."""
        from app.application_execution.answer_engine import ProfileDataProvider, generate_answer
        from app.application_execution.memory import MemoryStore

        result = generate_answer(
            "Are you authorized to work?",
            MemoryStore(),
            ProfileDataProvider({}),
        )
        assert result.needs_user_input is True
        assert result.classification.sensitivity == "HIGH"

    def test_unsupported_claim_not_invented(self):
        """Engine must not invent facts not in profile or memory."""
        from app.application_execution.answer_engine import ProfileDataProvider, generate_answer
        from app.application_execution.memory import MemoryStore

        profile = ProfileDataProvider({"first_name": "John"})
        result = generate_answer(
            "Why are you interested in this role?",
            MemoryStore(),
            profile,
        )
        # No motivation in profile or memory -> needs user input, no invented answer
        assert result.needs_user_input is True
        assert result.generated_answer is None


# ---------------------------------------------------------------------------
# Checkpoint Tests
# ---------------------------------------------------------------------------

class TestCheckpoints:
    """Tests for checkpointing."""

    def test_save_and_retrieve(self):
        store = CheckpointStore()
        cp = Checkpoint(
            run_id="run_123",
            checkpoint_type=CheckpointType.FORM_INSPECTED,
            step_number=1,
            state_snapshot={"fields_found": 5},
        )
        store.save(cp)
        latest = store.get_latest("run_123")
        assert latest is not None
        assert latest.checkpoint_type == CheckpointType.FORM_INSPECTED

    def test_can_resume(self):
        store = CheckpointStore()
        cp = Checkpoint(
            run_id="run_123",
            checkpoint_type=CheckpointType.FIELDS_FILLED,
            step_number=3,
        )
        store.save(cp)
        assert store.can_resume("run_123") is True

    def test_cannot_resume_after_submission(self):
        store = CheckpointStore()
        cp = Checkpoint(
            run_id="run_123",
            checkpoint_type=CheckpointType.SUBMISSION_CONFIRMED,
            step_number=5,
        )
        store.save(cp)
        assert store.can_resume("run_123") is False

    def test_create_helpers(self):
        cp = create_form_inspected_checkpoint("run_123", 1, 5, "https://example.com")
        assert cp.checkpoint_type == CheckpointType.FORM_INSPECTED
        assert cp.state_snapshot["fields_found"] == 5

    def test_resume_point(self):
        store = CheckpointStore()
        cp = Checkpoint(
            run_id="run_123",
            checkpoint_type=CheckpointType.FIELDS_FILLED,
            step_number=3,
            fields_filled={"email": "test@example.com"},
        )
        store.save(cp)
        point = store.get_resume_point("run_123")
        assert point["can_resume"] is True
        assert point["fields_filled"]["email"] == "test@example.com"


# ---------------------------------------------------------------------------
# Human Approval Tests
# ---------------------------------------------------------------------------

class TestHumanApproval:
    """Tests for human approval."""

    def test_request_approval(self):
        store = ApprovalStore()
        request = store.request_approval(
            "run_123",
            "SUBMIT_APPLICATION",
            reason="Submitting to Google",
        )
        assert request.status == ApprovalStatus.PENDING

    def test_grant_approval(self):
        store = ApprovalStore()
        store.request_approval("run_123", "SUBMIT_APPLICATION")
        granted = store.grant_approval("run_123", "SUBMIT_APPLICATION")
        assert granted.status == ApprovalStatus.GRANTED

    def test_deny_approval(self):
        store = ApprovalStore()
        store.request_approval("run_123", "SUBMIT_APPLICATION")
        denied = store.deny_approval("run_123", "SUBMIT_APPLICATION")
        assert denied.status == ApprovalStatus.DENIED

    def test_needs_approval_submit(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed("SUBMIT_APPLICATION", policy=policy)
        assert needs is True
        assert "always requires" in reason.lower()

    def test_needs_approval_high_sensitivity(self):
        policy = ApprovalPolicy()
        needs, reason = check_approval_needed(
            "AUTO_FILL_SENSITIVE",
            sensitivity="HIGH",
            policy=policy,
        )
        assert needs is True

    def test_no_approval_low_sensitivity(self):
        policy = ApprovalPolicy()
        needs, _ = check_approval_needed(
            "AUTO_FILL_SENSITIVE",
            sensitivity="LOW",
            policy=policy,
        )
        assert needs is False


# ---------------------------------------------------------------------------
# Analytics Tests
# ---------------------------------------------------------------------------

class TestAnalytics:
    """Tests for analytics."""

    def test_get_or_create_metrics(self):
        store = AnalyticsStore()
        metrics = store.get_or_create("run_123")
        assert metrics.run_id == "run_123"

    def test_record_field_mapping(self):
        store = AnalyticsStore()
        store.record_field_mapping("EMAIL", "EXACT_ALIAS", "HIGH", True)
        stats = store.get_field_mapping_accuracy()
        assert "EMAIL" in stats
        assert stats["EMAIL"] == 100.0

    def test_overall_stats(self):
        store = AnalyticsStore()
        metrics = store.get_or_create("run_123")
        metrics.total_fields = 10
        metrics.mapped_fields = 8
        metrics.filled_fields = 6
        stats = store.get_overall_stats()
        assert stats["total_runs"] == 1
        assert stats["mapping_accuracy"] == 80.0


# ---------------------------------------------------------------------------
# Security Tests
# ---------------------------------------------------------------------------

class TestSecurity:
    """Tests for security controls."""

    def test_check_auto_fill_allowed(self):
        controller = SecurityController()
        check = controller.check_auto_fill("EMAIL", "test@example.com", "USER_VERIFIED")
        assert check.allowed is True

    def test_check_auto_fill_denied(self):
        controller = SecurityController()
        check = controller.check_auto_fill("WORK_AUTHORIZATION", "Yes", "UNVERIFIED")
        assert check.allowed is False

    def test_mask_value(self):
        controller = SecurityController()
        masked = controller.mask_value("sensitive@email.com", "EMAIL")
        assert masked != "sensitive@email.com"
        assert len(masked) == len("sensitive@email.com")

    def test_validate_email(self):
        assert validate_email("test@example.com")[0] is True
        assert validate_email("invalid")[0] is False

    def test_validate_phone(self):
        assert validate_phone("+1-234-567-8900")[0] is True
        assert validate_phone("12")[0] is False

    def test_validate_url(self):
        assert validate_url("https://example.com")[0] is True
        assert validate_url("example.com")[0] is False

    def test_field_classification(self):
        assert FIELD_CLASSIFICATION["EMAIL"] == "PERSONAL"
        assert FIELD_CLASSIFICATION["SALARY_EXPECTATION"] == "FINANCIAL"
        assert FIELD_CLASSIFICATION["WORK_AUTHORIZATION"] == "AUTHORIZATION"


# ---------------------------------------------------------------------------
# Pipeline Tests
# ---------------------------------------------------------------------------

class TestPipeline:
    """Tests for the mapping pipeline."""

    def test_run_pipeline_basic(self):
        detected = [
            DetectedField(label="first name", kind="text"),
            DetectedField(label="email address", kind="text"),
        ]
        profile = {"first_name": "John", "email": "john@example.com"}
        result = run_pipeline(detected, profile=profile)
        assert len(result.fields) == 2
        assert result.ready_fields >= 0

    def test_detect_contradictions(self):
        fields = [
            PipelineField(
                raw_label="Full Name",
                mapping=FieldMapping(canonical="FULL_NAME"),
                final_value="John Doe",
            ),
            PipelineField(
                raw_label="First Name",
                mapping=FieldMapping(canonical="FIRST_NAME"),
                final_value="Jane",
            ),
        ]
        contradictions = detect_contradictions(fields)
        assert len(contradictions) > 0

    def test_pipeline_stages(self):
        detected = [DetectedField(label="email", kind="text")]
        result = run_pipeline(detected)
        assert "INSPECT" in result.stages_completed
        assert "MATCH" in result.stages_completed
        assert "VALIDATE" in result.stages_completed
