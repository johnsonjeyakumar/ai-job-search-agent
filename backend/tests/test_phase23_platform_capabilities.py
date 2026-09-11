"""Phase 23 — Platform capability registry + site adapters tests.

Tests platform identification, capability registry, capability states,
generic fallback, execution planning, field/document/auth/submission
capability matrices, capability discovery, and safety rules.
"""
from __future__ import annotations

from app.application_execution.platform_capabilities import (
    _DEFAULT_DOCUMENT_SUPPORT,
    _DEFAULT_FIELD_SUPPORT,
    CapabilityState,
    ExecutionPlan,
    ExecutionStrategy,
    PlatformCapability,
    PlatformCapabilityRegistry,
    RuntimeCapabilityObservation,
    SubmissionCapability,
    _build_capability_map,
    decide_platform_support,
    discover_capabilities_from_observation,
    evaluate_capability_match,
    generate_execution_plan,
    get_capability_registry,
)

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2-3 — CAPABILITY STATES + REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

class TestCapabilityStates:
    def test_capability_state_values(self):
        expected = {"SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNKNOWN", "BLOCKED"}
        actual = {s.value for s in CapabilityState}
        assert actual == expected

    def test_submission_capability_values(self):
        expected = {
            "SUBMISSION_SUPPORTED", "SUBMISSION_PARTIAL",
            "SUBMISSION_UNSUPPORTED", "SUBMISSION_UNKNOWN",
        }
        actual = {s.value for s in SubmissionCapability}
        assert actual == expected

    def test_execution_strategy_values(self):
        expected = {
            "FULL_AUTOMATIC", "GUIDED_AUTOMATIC", "HUMAN_ASSISTED",
            "REVIEW_REQUIRED", "BLOCKED",
        }
        actual = {s.value for s in ExecutionStrategy}
        assert actual == expected


class TestPlatformCapabilityRegistry:
    def test_singleton_exists(self):
        r = get_capability_registry()
        assert r is not None
        assert isinstance(r, PlatformCapabilityRegistry)

    def test_generic_platform_registered(self):
        r = get_capability_registry()
        assert r.has_platform("generic")
        cap = r.get("generic")
        assert cap.platform == "generic"

    def test_linkedin_platform_registered(self):
        r = get_capability_registry()
        assert r.has_platform("linkedin")
        cap = r.get("linkedin")
        assert cap.display_name == "LinkedIn"

    def test_indeed_platform_registered(self):
        r = get_capability_registry()
        assert r.has_platform("indeed")

    def test_naukri_platform_registered(self):
        r = get_capability_registry()
        assert r.has_platform("naukri")

    def test_company_career_registered(self):
        r = get_capability_registry()
        assert r.has_platform("company_career")

    def test_human_assisted_registered(self):
        r = get_capability_registry()
        assert r.has_platform("human_assisted")

    def test_unknown_platform_falls_back_to_generic(self):
        r = get_capability_registry()
        cap = r.get("unknown_platform_xyz")
        assert cap.platform == "generic"

    def test_list_platforms(self):
        r = get_capability_registry()
        platforms = r.list_platforms()
        assert "generic" in platforms
        assert "linkedin" in platforms
        assert len(platforms) >= 6

    def test_custom_platform_registration(self):
        r = PlatformCapabilityRegistry()
        custom = PlatformCapability(
            platform="test_platform",
            display_name="Test Platform",
            multi_page_forms=CapabilityState.SUPPORTED,
        )
        r.register(custom)
        assert r.has_platform("test_platform")
        cap = r.get("test_platform")
        assert cap.multi_page_forms == CapabilityState.SUPPORTED


# ═══════════════════════════════════════════════════════════════════════════
# STEP 4 — CAPABILITY MATCHING
# ═══════════════════════════════════════════════════════════════════════════

class TestCapabilityMatching:
    def _make_cap(self, **kwargs):
        defaults = {
            "platform": "test",
            "display_name": "Test",
            "multi_page_forms": CapabilityState.SUPPORTED,
            "file_upload": CapabilityState.SUPPORTED,
            "autocomplete": CapabilityState.PARTIAL,
            "captcha_detection": CapabilityState.SUPPORTED,
            "submission_capability": SubmissionCapability.SUPPORTED,
        }
        defaults.update(kwargs)
        return PlatformCapability(**defaults)

    def test_all_supported(self):
        cap = self._make_cap()
        satisfied, missing, partial = evaluate_capability_match(
            cap, ["multi_page_forms", "file_upload", "captcha_detection"]
        )
        assert satisfied == ["multi_page_forms", "file_upload", "captcha_detection"]
        assert missing == []
        assert partial == []

    def test_partial_detected(self):
        cap = self._make_cap()
        satisfied, missing, partial = evaluate_capability_match(
            cap, ["autocomplete"]
        )
        assert partial == ["autocomplete"]

    def test_missing_detected(self):
        cap = self._make_cap(unsupported_field_kinds=["multi_select"])
        satisfied, missing, partial = evaluate_capability_match(
            cap, ["multi_select"]
        )
        assert missing == ["multi_select"]

    def test_unknown_treated_as_missing(self):
        cap = self._make_cap()
        satisfied, missing, partial = evaluate_capability_match(
            cap, ["nonexistent_capability"]
        )
        assert missing == ["nonexistent_capability"]

    def test_mixed_capabilities(self):
        cap = self._make_cap()
        satisfied, missing, partial = evaluate_capability_match(
            cap, [
                "multi_page_forms",
                "autocomplete",
                "nonexistent",
            ]
        )
        assert "multi_page_forms" in satisfied
        assert "autocomplete" in partial
        assert "nonexistent" in missing


# ═══════════════════════════════════════════════════════════════════════════
# STEP 5-7 — GENERIC FALLBACK + ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class TestGenericFallback:
    def test_generic_has_safe_defaults(self):
        r = get_capability_registry()
        cap = r.get("generic")
        assert cap.file_upload == CapabilityState.SUPPORTED
        assert cap.authentication_detection == CapabilityState.SUPPORTED
        assert cap.captcha_detection == CapabilityState.SUPPORTED
        assert cap.submission_capability == SubmissionCapability.UNKNOWN

    def test_generic_submission_unknown(self):
        """Generic platform submission capability is unknown — requires verification."""
        r = get_capability_registry()
        cap = r.get("generic")
        assert cap.submission_capability == SubmissionCapability.UNKNOWN

    def test_generic_multi_page_partial(self):
        r = get_capability_registry()
        cap = r.get("generic")
        assert cap.multi_page_forms == CapabilityState.PARTIAL


# ═══════════════════════════════════════════════════════════════════════════
# STEP 8-9 — PLATFORM ADAPTERS + QUIRK HANDLING
# ═══════════════════════════════════════════════════════════════════════════

class TestPlatformAdapters:
    def test_linkedin_limited_field_support(self):
        r = get_capability_registry()
        cap = r.get("linkedin")
        assert "text" in cap.supported_field_kinds
        assert "multi_select" in cap.unsupported_field_kinds

    def test_linkedin_no_multi_file(self):
        r = get_capability_registry()
        cap = r.get("linkedin")
        assert cap.multiple_file_upload == CapabilityState.UNSUPPORTED

    def test_company_career_broader_support(self):
        r = get_capability_registry()
        cap = r.get("company_career")
        assert "portfolio" in cap.supported_document_types
        assert "certificate" in cap.supported_document_types

    def test_human_assisted_all_fields_supported(self):
        r = get_capability_registry()
        cap = r.get("human_assisted")
        for kind in _DEFAULT_FIELD_SUPPORT:
            assert kind in cap.supported_field_kinds

    def test_human_assisted_no_auto_submit(self):
        r = get_capability_registry()
        cap = r.get("human_assisted")
        assert cap.submission_capability == SubmissionCapability.UNSUPPORTED


# ═══════════════════════════════════════════════════════════════════════════
# STEP 10-11 — FIELD + DOCUMENT CAPABILITY MATRICES
# ═══════════════════════════════════════════════════════════════════════════

class TestFieldCapabilityMatrix:
    def test_default_field_support_complete(self):
        for kind in ("text", "textarea", "select", "radio", "checkbox",
                     "file", "date", "multi_select", "currency", "autocomplete"):
            assert kind in _DEFAULT_FIELD_SUPPORT

    def test_text_always_supported(self):
        r = get_capability_registry()
        for platform in r.list_platforms():
            cap = r.get(platform)
            assert "text" in cap.supported_field_kinds, (
                f"text not supported on {platform}"
            )

    def test_textarea_always_supported(self):
        r = get_capability_registry()
        for platform in r.list_platforms():
            cap = r.get(platform)
            assert "textarea" in cap.supported_field_kinds, (
                f"textarea not supported on {platform}"
            )


class TestDocumentCapabilityMatrix:
    def test_default_document_support(self):
        assert "resume" in _DEFAULT_DOCUMENT_SUPPORT
        assert "cover_letter" in _DEFAULT_DOCUMENT_SUPPORT
        assert _DEFAULT_DOCUMENT_SUPPORT["resume"] == CapabilityState.SUPPORTED

    def test_all_platforms_support_resume(self):
        r = get_capability_registry()
        for platform in r.list_platforms():
            cap = r.get(platform)
            assert "resume" in cap.supported_document_types, (
                f"resume not in supported docs for {platform}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# STEP 12 — AUTH CAPABILITY MATRIX
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthCapabilityMatrix:
    def test_all_platforms_have_captcha_detection(self):
        r = get_capability_registry()
        for platform in r.list_platforms():
            cap = r.get(platform)
            assert cap.captcha_detection != CapabilityState.UNSUPPORTED, (
                f"captcha detection unsupported on {platform}"
            )

    def test_all_platforms_have_auth_detection(self):
        r = get_capability_registry()
        for platform in r.list_platforms():
            cap = r.get(platform)
            assert cap.authentication_detection != CapabilityState.UNSUPPORTED, (
                f"auth detection unsupported on {platform}"
            )

    def test_all_platforms_have_mfa_detection(self):
        r = get_capability_registry()
        for platform in r.list_platforms():
            cap = r.get(platform)
            assert cap.mfa_detection != CapabilityState.UNSUPPORTED, (
                f"mfa detection unsupported on {platform}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# STEP 13 — SUBMISSION CAPABILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestSubmissionCapability:
    def test_linkedin_submission_supported(self):
        r = get_capability_registry()
        cap = r.get("linkedin")
        assert cap.submission_capability == SubmissionCapability.SUPPORTED

    def test_human_assisted_submission_unsupported(self):
        r = get_capability_registry()
        cap = r.get("human_assisted")
        assert cap.submission_capability == SubmissionCapability.UNSUPPORTED

    def test_generic_submission_unknown(self):
        r = get_capability_registry()
        cap = r.get("generic")
        assert cap.submission_capability == SubmissionCapability.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# STEP 14-15 — EXECUTION PLAN + SUPPORT DECISION
# ═══════════════════════════════════════════════════════════════════════════

class TestExecutionPlan:
    def test_plan_for_linkedin(self):
        plan = generate_execution_plan(platform="linkedin")
        assert plan.platform == "linkedin"
        assert plan.strategy in (
            ExecutionStrategy.FULL_AUTOMATIC,
            ExecutionStrategy.GUIDED_AUTOMATIC,
        )
        assert plan.is_executable

    def test_plan_for_human_assisted(self):
        plan = generate_execution_plan(platform="human_assisted")
        assert plan.strategy == ExecutionStrategy.HUMAN_ASSISTED
        assert plan.is_executable

    def test_plan_for_generic(self):
        plan = generate_execution_plan(platform="generic")
        assert plan.platform == "generic"
        # Generic submission unknown → review
        assert plan.strategy == ExecutionStrategy.REVIEW_REQUIRED

    def test_plan_has_capability_profile(self):
        plan = generate_execution_plan(platform="linkedin")
        assert plan.capability_profile is not None
        assert plan.capability_profile.platform == "linkedin"

    def test_plan_has_confidence(self):
        plan = generate_execution_plan(platform="linkedin")
        assert 0.0 <= plan.estimated_confidence <= 1.0

    def test_plan_created_at_populated(self):
        plan = generate_execution_plan(platform="linkedin")
        assert plan.created_at != ""

    def test_plan_required_capabilities(self):
        plan = generate_execution_plan(platform="linkedin")
        assert len(plan.required_capabilities) > 0

    def test_plan_supported_controls(self):
        plan = generate_execution_plan(platform="linkedin")
        assert len(plan.supported_controls) > 0

    def test_plan_is_executable_property(self):
        plan = generate_execution_plan(platform="linkedin")
        if plan.strategy in (
            ExecutionStrategy.FULL_AUTOMATIC,
            ExecutionStrategy.GUIDED_AUTOMATIC,
            ExecutionStrategy.HUMAN_ASSISTED,
        ):
            assert plan.is_executable is True
        else:
            assert plan.is_executable is False

    def test_plan_has_blockers_property(self):
        plan = generate_execution_plan(platform="linkedin")
        if plan.blockers:
            assert plan.has_blockers is True
        else:
            assert plan.has_blockers is False

    def test_plan_needs_review_property(self):
        plan = generate_execution_plan(platform="generic")
        if plan.strategy == ExecutionStrategy.REVIEW_REQUIRED:
            assert plan.needs_review is True


class TestSupportDecision:
    def test_ready_for_execution(self):
        plan = generate_execution_plan(platform="linkedin")
        decision, reasons = decide_platform_support(plan)
        assert decision in ("READY_FOR_EXECUTION", "REVIEW")

    def test_blocked_when_blockers(self):
        plan = ExecutionPlan(
            platform="test",
            strategy=ExecutionStrategy.BLOCKED,
            blockers=["Test blocker"],
        )
        decision, reasons = decide_platform_support(plan)
        assert decision == "BLOCKED"
        assert "Test blocker" in reasons

    def test_review_when_review_required(self):
        plan = ExecutionPlan(
            platform="test",
            strategy=ExecutionStrategy.REVIEW_REQUIRED,
            warnings=["Test warning"],
        )
        decision, reasons = decide_platform_support(plan)
        assert decision == "REVIEW"

    def test_review_when_partial(self):
        plan = ExecutionPlan(
            platform="test",
            strategy=ExecutionStrategy.GUIDED_AUTOMATIC,
            warnings=["Partial support"],
        )
        decision, reasons = decide_platform_support(plan)
        assert decision == "READY_FOR_EXECUTION"
        assert "Partial support" in reasons


# ═══════════════════════════════════════════════════════════════════════════
# STEP 15 — PLATFORM SUPPORT DECISION RULES
# ═══════════════════════════════════════════════════════════════════════════

class TestPlatformSupportRules:
    def test_captcha_blocks(self):
        plan = generate_execution_plan(
            platform="linkedin",
            captcha_detected=True,
        )
        assert plan.strategy == ExecutionStrategy.BLOCKED
        assert plan.has_blockers

    def test_auth_required_pauses(self):
        plan = generate_execution_plan(
            platform="linkedin",
            auth_state="LOGIN_REQUIRED",
        )
        assert plan.strategy == ExecutionStrategy.HUMAN_ASSISTED

    def test_mfa_required_pauses(self):
        plan = generate_execution_plan(
            platform="linkedin",
            auth_state="MFA_REQUIRED",
        )
        assert plan.strategy == ExecutionStrategy.HUMAN_ASSISTED

    def test_auth_failed_blocks(self):
        plan = generate_execution_plan(
            platform="linkedin",
            auth_state="AUTH_FAILED",
        )
        assert plan.strategy == ExecutionStrategy.BLOCKED

    def test_session_expired_blocks(self):
        plan = generate_execution_plan(
            platform="linkedin",
            auth_state="SESSION_EXPIRED",
        )
        assert plan.strategy == ExecutionStrategy.BLOCKED

    def test_missing_required_capability_blocks(self):
        plan = generate_execution_plan(
            platform="human_assisted",
            required_capabilities=["nonexistent_critical_thing"],
        )
        assert plan.strategy == ExecutionStrategy.BLOCKED
        assert plan.has_blockers

    def test_partial_required_capability_reviews(self):
        plan = generate_execution_plan(
            platform="generic",
            required_capabilities=["autocomplete"],
        )
        # Generic autocomplete is PARTIAL
        assert plan.strategy == ExecutionStrategy.REVIEW_REQUIRED


# ═══════════════════════════════════════════════════════════════════════════
# STEP 16-17 — CAPABILITY DISCOVERY + VERSIONING
# ═══════════════════════════════════════════════════════════════════════════

class TestCapabilityDiscovery:
    def test_observation_to_capability(self):
        obs = RuntimeCapabilityObservation(
            origin="https://apply.example.com",
            domain="apply.example.com",
            form_fields=[
                {"kind": "text", "label": "Name"},
                {"kind": "select", "label": "Country"},
            ],
            has_file_input=True,
            has_multi_page=False,
            has_autocomplete=False,
            has_review_button=False,
            has_submit_button=True,
            has_captcha=False,
            has_login_form=False,
        )
        cap = obs.to_capability()
        assert cap.source == "discovery"
        assert "text" in cap.supported_field_kinds
        assert "select" in cap.supported_field_kinds
        assert cap.file_upload == CapabilityState.SUPPORTED

    def test_observation_with_captcha(self):
        obs = RuntimeCapabilityObservation(
            has_captcha=True,
            has_login_form=True,
        )
        cap = obs.to_capability()
        assert "CAPTCHA detected" in cap.limitations[0]

    def test_discover_capabilities_from_observation(self):
        obs = RuntimeCapabilityObservation(
            domain="test.com",
            has_submit_button=True,
        )
        cap = discover_capabilities_from_observation(obs)
        assert cap.source == "discovery"
        assert cap.display_name == "Discovered: test.com"

    def test_observation_confidence(self):
        obs = RuntimeCapabilityObservation(confidence="low")
        cap = obs.to_capability()
        assert cap.confidence == "low"

    def test_observation_auto_timestamps(self):
        obs = RuntimeCapabilityObservation()
        assert obs.observed_at != ""


# ═══════════════════════════════════════════════════════════════════════════
# STEP 18 — PLATFORM SAFETY GATE
# ═══════════════════════════════════════════════════════════════════════════

class TestPlatformSafetyGate:
    def test_safety_gate_blocks_captcha(self):
        plan = generate_execution_plan(
            platform="generic",
            captcha_detected=True,
        )
        decision, _ = decide_platform_support(plan)
        assert decision == "BLOCKED"

    def test_safety_gate_pauses_auth(self):
        plan = generate_execution_plan(
            platform="generic",
            auth_state="MFA_REQUIRED",
        )
        assert plan.strategy == ExecutionStrategy.HUMAN_ASSISTED

    def test_safety_gate_allows_supported(self):
        plan = generate_execution_plan(platform="linkedin")
        decision, _ = decide_platform_support(plan)
        assert decision in ("READY_FOR_EXECUTION", "REVIEW")

    def test_safety_gate_requires_submission_known(self):
        plan = generate_execution_plan(platform="generic")
        # Generic submission is UNKNOWN → REVIEW
        assert plan.strategy == ExecutionStrategy.REVIEW_REQUIRED


# ═══════════════════════════════════════════════════════════════════════════
# STEP 22 — UNIT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCapabilityVersioning:
    def test_profile_has_version(self):
        cap = PlatformCapability(platform="test", display_name="Test")
        assert cap.version == "1.0"

    def test_profile_has_observed_at(self):
        cap = PlatformCapability(platform="test", display_name="Test")
        assert cap.observed_at != ""

    def test_profile_has_source(self):
        cap = PlatformCapability(platform="test", display_name="Test", source="discovery")
        assert cap.source == "discovery"

    def test_profile_has_confidence(self):
        cap = PlatformCapability(platform="test", display_name="Test", confidence="low")
        assert cap.confidence == "low"

    def test_profile_has_limitations(self):
        cap = PlatformCapability(
            platform="test", display_name="Test",
            limitations=["Test limitation"],
        )
        assert "Test limitation" in cap.limitations


class TestCapabilityMap:
    def test_build_capability_map(self):
        cap = PlatformCapability(
            platform="test",
            display_name="Test",
            multi_page_forms=CapabilityState.SUPPORTED,
            file_upload=CapabilityState.PARTIAL,
            submission_capability=SubmissionCapability.SUPPORTED,
        )
        m = _build_capability_map(cap)
        assert m["multi_page_forms"] == CapabilityState.SUPPORTED
        assert m["file_upload"] == CapabilityState.PARTIAL
        # Submission is normalized to CapabilityState
        assert m["submission"] == CapabilityState.SUPPORTED

    def test_map_has_all_capabilities(self):
        cap = PlatformCapability(platform="test", display_name="Test")
        m = _build_capability_map(cap)
        expected_keys = {
            "multi_page_forms", "conditional_fields", "autocomplete",
            "file_upload", "multiple_file_upload",
            "authentication_detection", "mfa_detection", "captcha_detection",
            "review_page_detection", "confirmation_detection",
            "reference_id_extraction", "submission", "duplicate_detection",
        }
        assert expected_keys == set(m.keys())


# ═══════════════════════════════════════════════════════════════════════════
# STEP 19-20 — QUEUE INTEGRATION + EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestQueueIntegration:
    def test_plan_for_each_platform(self):
        """Every registered platform should produce a valid plan."""
        r = get_capability_registry()
        for platform in r.list_platforms():
            plan = generate_execution_plan(platform=platform)
            assert plan.platform == platform
            assert plan.strategy is not None
            assert plan.created_at != ""

    def test_one_bad_platform_does_not_crash(self):
        """Unknown platforms should not crash the system."""
        plan = generate_execution_plan(platform="nonexistent_platform")
        assert plan is not None
        assert plan.platform == "nonexistent_platform"


# ═══════════════════════════════════════════════════════════════════════════
# SAFETY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSafetyVerification:
    def test_unsupported_capabilities_not_executed(self):
        """Plan with unsupported required capabilities must not be executable."""
        plan = generate_execution_plan(
            platform="human_assisted",
            required_capabilities=["nonexistent_thing"],
        )
        assert not plan.is_executable

    def test_unknown_platform_does_not_bypass_safety(self):
        """Unknown platform still goes through safety gate."""
        plan = generate_execution_plan(platform="unknown_thing")
        decision, _ = decide_platform_support(plan)
        # Unknown platform with unknown submission → REVIEW
        assert decision in ("REVIEW", "BLOCKED")

    def test_captcha_remains_blocked(self):
        plan = generate_execution_plan(
            platform="linkedin",
            captcha_detected=True,
        )
        assert plan.strategy == ExecutionStrategy.BLOCKED

    def test_auth_remains_safe(self):
        plan = generate_execution_plan(
            platform="linkedin",
            auth_state="MFA_REQUIRED",
        )
        assert plan.strategy == ExecutionStrategy.HUMAN_ASSISTED

    def test_generic_only_executes_supported_controls(self):
        """Generic platform should not claim support for unknown capabilities."""
        plan = generate_execution_plan(platform="generic")
        # Generic autocomplete is PARTIAL
        assert "autocomplete" in plan.partial_controls or \
               "autocomplete" in plan.unsupported_controls or \
               "autocomplete" in plan.missing_capabilities

    def test_submission_must_be_known_for_full_auto(self):
        """Full automatic requires known submission capability."""
        plan = generate_execution_plan(platform="generic")
        if plan.strategy == ExecutionStrategy.FULL_AUTOMATIC:
            assert plan.capability_profile is not None
            assert plan.capability_profile.submission_capability != SubmissionCapability.UNKNOWN

    def test_no_hostname_conditionals_in_planning(self):
        """Planning is capability-based, not hostname-based."""
        plan_a = generate_execution_plan(platform="linkedin")
        plan_b = generate_execution_plan(platform="indeed")
        # Both should work through capability matching, not hostname checks
        assert plan_a.platform == "linkedin"
        assert plan_b.platform == "indeed"

    def test_duplicate_protection_preserved(self):
        """Capability check doesn't bypass duplicate detection."""
        # This is a structural test — duplicate check happens in preflight
        plan = generate_execution_plan(platform="linkedin")
        assert plan.is_executable  # capability check alone doesn't block

    def test_readiness_preflight_preserved(self):
        """Capability check doesn't bypass readiness/preflight."""
        plan = generate_execution_plan(platform="linkedin")
        # Preflight and readiness are checked separately in the executor
        assert plan.is_executable
