"""Platform capability registry and execution planning (Phase 23).

Provides a deterministic, platform-aware execution layer. The system
identifies the application platform, loads its capability profile,
checks supported features, and selects the safest execution strategy.

Architecture:
    Executor → Platform Resolver → Capability Registry
    → Execution Plan → Existing Execution Engine

Safety rules:
    - Unknown capabilities must NOT be treated as supported.
    - Unsupported or ambiguous platforms fall back safely to REVIEW.
    - Never bypass CAPTCHA, anti-bot, authentication, or rate limits.
    - Never fabricate platform support claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

# ---------------------------------------------------------------------------
# Capability states
# ---------------------------------------------------------------------------

class CapabilityState(str, Enum):
    """Deterministic capability classification."""

    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Submission capability
# ---------------------------------------------------------------------------

class SubmissionCapability(str, Enum):
    """Submission support classification."""

    SUPPORTED = "SUBMISSION_SUPPORTED"
    PARTIAL = "SUBMISSION_PARTIAL"
    UNSUPPORTED = "SUBMISSION_UNSUPPORTED"
    UNKNOWN = "SUBMISSION_UNKNOWN"


# ---------------------------------------------------------------------------
# Execution strategy
# ---------------------------------------------------------------------------

class ExecutionStrategy(str, Enum):
    """How to execute on a given platform."""

    FULL_AUTOMATIC = "FULL_AUTOMATIC"
    GUIDED_AUTOMATIC = "GUIDED_AUTOMATIC"
    HUMAN_ASSISTED = "HUMAN_ASSISTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


# ---------------------------------------------------------------------------
# Platform capability profile
# ---------------------------------------------------------------------------

@dataclass
class PlatformCapability:
    """Complete capability profile for a platform."""

    platform: str
    display_name: str
    version: str = "1.0"
    observed_at: str = ""

    # Form capabilities
    multi_page_forms: str = CapabilityState.UNKNOWN
    conditional_fields: str = CapabilityState.UNKNOWN
    autocomplete: str = CapabilityState.UNKNOWN

    # Document capabilities
    file_upload: str = CapabilityState.UNKNOWN
    multiple_file_upload: str = CapabilityState.UNKNOWN
    supported_document_types: list[str] = field(default_factory=list)

    # Auth capabilities
    authentication_detection: str = CapabilityState.UNKNOWN
    mfa_detection: str = CapabilityState.UNKNOWN
    captcha_detection: str = CapabilityState.UNKNOWN

    # Submission capabilities
    review_page_detection: str = CapabilityState.UNKNOWN
    confirmation_detection: str = CapabilityState.UNKNOWN
    reference_id_extraction: str = CapabilityState.UNKNOWN
    submission_capability: str = SubmissionCapability.UNKNOWN
    duplicate_detection_support: str = CapabilityState.UNKNOWN

    # Field support
    supported_field_kinds: list[str] = field(default_factory=list)
    unsupported_field_kinds: list[str] = field(default_factory=list)

    # Known limitations
    limitations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # Source of capability data
    source: str = "registry"  # registry | discovery | adapter
    confidence: str = "high"  # high | medium | low

    def __post_init__(self):
        if not self.observed_at:
            self.observed_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Field capability matrix
# ---------------------------------------------------------------------------

# Default field support for generic platforms
_DEFAULT_FIELD_SUPPORT: dict[str, str] = {
    "text": CapabilityState.SUPPORTED,
    "textarea": CapabilityState.SUPPORTED,
    "select": CapabilityState.SUPPORTED,
    "radio": CapabilityState.SUPPORTED,
    "checkbox": CapabilityState.SUPPORTED,
    "file": CapabilityState.SUPPORTED,
    "date": CapabilityState.SUPPORTED,
    "multi_select": CapabilityState.PARTIAL,
    "currency": CapabilityState.SUPPORTED,
    "autocomplete": CapabilityState.PARTIAL,
}

# Known unsupported field kinds per platform
_PLATFORM_FIELD_LIMITATIONS: dict[str, dict[str, str]] = {
    "generic": {
        "multi_select": CapabilityState.PARTIAL,
        "autocomplete": CapabilityState.PARTIAL,
    },
}


# ---------------------------------------------------------------------------
# Document capability matrix
# ---------------------------------------------------------------------------

_DEFAULT_DOCUMENT_SUPPORT: dict[str, CapabilityState] = {
    "resume": CapabilityState.SUPPORTED,
    "cover_letter": CapabilityState.SUPPORTED,
    "portfolio": CapabilityState.PARTIAL,
    "certificate": CapabilityState.PARTIAL,
    "other": CapabilityState.UNKNOWN,
}

_DEFAULT_ACCEPTED_EXTENSIONS: dict[str, list[str]] = {
    "resume": [".pdf", ".doc", ".docx", ".txt", ".rtf"],
    "cover_letter": [".pdf", ".doc", ".docx", ".txt"],
    "portfolio": [".pdf", ".doc", ".docx", ".txt", ".zip"],
    "certificate": [".pdf", ".jpg", ".jpeg", ".png"],
    "other": [".pdf", ".doc", ".docx", ".txt"],
}


# ---------------------------------------------------------------------------
# Platform capability registry
# ---------------------------------------------------------------------------

class PlatformCapabilityRegistry:
    """Registry of platform capability profiles.

    Provides deterministic capability lookup and execution planning.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, PlatformCapability] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default capability profiles for known platforms."""

        # Generic platform — safe defaults
        self.register(PlatformCapability(
            platform="generic",
            display_name="Application page",
            multi_page_forms=CapabilityState.PARTIAL,
            conditional_fields=CapabilityState.PARTIAL,
            autocomplete=CapabilityState.PARTIAL,
            file_upload=CapabilityState.SUPPORTED,
            multiple_file_upload=CapabilityState.PARTIAL,
            supported_document_types=["resume", "cover_letter"],
            authentication_detection=CapabilityState.SUPPORTED,
            mfa_detection=CapabilityState.SUPPORTED,
            captcha_detection=CapabilityState.SUPPORTED,
            review_page_detection=CapabilityState.PARTIAL,
            confirmation_detection=CapabilityState.PARTIAL,
            reference_id_extraction=CapabilityState.PARTIAL,
            submission_capability=SubmissionCapability.UNKNOWN,
            duplicate_detection_support=CapabilityState.UNKNOWN,
            supported_field_kinds=list(_DEFAULT_FIELD_SUPPORT.keys()),
            limitations=[
                "Generic platform — capabilities discovered at runtime.",
                "Submission capability must be verified before auto-submit.",
            ],
            source="registry",
        ))

        # LinkedIn
        self.register(PlatformCapability(
            platform="linkedin",
            display_name="LinkedIn",
            multi_page_forms=CapabilityState.SUPPORTED,
            conditional_fields=CapabilityState.SUPPORTED,
            autocomplete=CapabilityState.PARTIAL,
            file_upload=CapabilityState.SUPPORTED,
            multiple_file_upload=CapabilityState.UNSUPPORTED,
            supported_document_types=["resume"],
            authentication_detection=CapabilityState.SUPPORTED,
            mfa_detection=CapabilityState.SUPPORTED,
            captcha_detection=CapabilityState.SUPPORTED,
            review_page_detection=CapabilityState.SUPPORTED,
            confirmation_detection=CapabilityState.SUPPORTED,
            reference_id_extraction=CapabilityState.PARTIAL,
            submission_capability=SubmissionCapability.SUPPORTED,
            duplicate_detection_support=CapabilityState.SUPPORTED,
            supported_field_kinds=[
                "text", "textarea", "select", "radio", "checkbox",
                "file", "date",
            ],
            unsupported_field_kinds=["multi_select", "autocomplete"],
            limitations=[
                "LinkedIn Easy Apply only.",
                "Multi-select fields not directly supported.",
                "Autocomplete requires special handling.",
            ],
            source="registry",
        ))

        # Indeed
        self.register(PlatformCapability(
            platform="indeed",
            display_name="Indeed",
            multi_page_forms=CapabilityState.SUPPORTED,
            conditional_fields=CapabilityState.SUPPORTED,
            autocomplete=CapabilityState.PARTIAL,
            file_upload=CapabilityState.SUPPORTED,
            multiple_file_upload=CapabilityState.UNSUPPORTED,
            supported_document_types=["resume", "cover_letter"],
            authentication_detection=CapabilityState.SUPPORTED,
            mfa_detection=CapabilityState.SUPPORTED,
            captcha_detection=CapabilityState.SUPPORTED,
            review_page_detection=CapabilityState.SUPPORTED,
            confirmation_detection=CapabilityState.SUPPORTED,
            reference_id_extraction=CapabilityState.PARTIAL,
            submission_capability=SubmissionCapability.SUPPORTED,
            duplicate_detection_support=CapabilityState.SUPPORTED,
            supported_field_kinds=[
                "text", "textarea", "select", "radio", "checkbox",
                "file", "date",
            ],
            unsupported_field_kinds=["multi_select", "autocomplete"],
            limitations=[
                "Indeed Apply only.",
                "External redirects not supported.",
            ],
            source="registry",
        ))

        # Naukri
        self.register(PlatformCapability(
            platform="naukri",
            display_name="Naukri",
            multi_page_forms=CapabilityState.SUPPORTED,
            conditional_fields=CapabilityState.SUPPORTED,
            autocomplete=CapabilityState.PARTIAL,
            file_upload=CapabilityState.SUPPORTED,
            multiple_file_upload=CapabilityState.UNSUPPORTED,
            supported_document_types=["resume"],
            authentication_detection=CapabilityState.SUPPORTED,
            mfa_detection=CapabilityState.SUPPORTED,
            captcha_detection=CapabilityState.SUPPORTED,
            review_page_detection=CapabilityState.PARTIAL,
            confirmation_detection=CapabilityState.PARTIAL,
            reference_id_extraction=CapabilityState.PARTIAL,
            submission_capability=SubmissionCapability.SUPPORTED,
            duplicate_detection_support=CapabilityState.SUPPORTED,
            supported_field_kinds=[
                "text", "textarea", "select", "radio", "checkbox",
                "file", "date",
            ],
            unsupported_field_kinds=["multi_select", "autocomplete"],
            limitations=[
                "Naukri Apply only.",
                "Limited autocomplete support.",
            ],
            source="registry",
        ))

        # Company career sites (generic ATS)
        self.register(PlatformCapability(
            platform="company_career",
            display_name="Company career site",
            multi_page_forms=CapabilityState.SUPPORTED,
            conditional_fields=CapabilityState.SUPPORTED,
            autocomplete=CapabilityState.PARTIAL,
            file_upload=CapabilityState.SUPPORTED,
            multiple_file_upload=CapabilityState.PARTIAL,
            supported_document_types=[
                "resume", "cover_letter", "portfolio", "certificate",
            ],
            authentication_detection=CapabilityState.SUPPORTED,
            mfa_detection=CapabilityState.SUPPORTED,
            captcha_detection=CapabilityState.SUPPORTED,
            review_page_detection=CapabilityState.PARTIAL,
            confirmation_detection=CapabilityState.PARTIAL,
            reference_id_extraction=CapabilityState.PARTIAL,
            submission_capability=SubmissionCapability.SUPPORTED,
            duplicate_detection_support=CapabilityState.UNKNOWN,
            supported_field_kinds=list(_DEFAULT_FIELD_SUPPORT.keys()),
            limitations=[
                "Capabilities vary by ATS provider.",
                "Submission verification required.",
            ],
            source="registry",
        ))

        # Human-assisted (always safe, never auto-submit)
        self.register(PlatformCapability(
            platform="human_assisted",
            display_name="Human-assisted application",
            multi_page_forms=CapabilityState.SUPPORTED,
            conditional_fields=CapabilityState.SUPPORTED,
            autocomplete=CapabilityState.SUPPORTED,
            file_upload=CapabilityState.SUPPORTED,
            multiple_file_upload=CapabilityState.SUPPORTED,
            supported_document_types=[
                "resume", "cover_letter", "portfolio", "certificate", "other",
            ],
            authentication_detection=CapabilityState.SUPPORTED,
            mfa_detection=CapabilityState.SUPPORTED,
            captcha_detection=CapabilityState.SUPPORTED,
            review_page_detection=CapabilityState.SUPPORTED,
            confirmation_detection=CapabilityState.SUPPORTED,
            reference_id_extraction=CapabilityState.SUPPORTED,
            submission_capability=SubmissionCapability.UNSUPPORTED,
            duplicate_detection_support=CapabilityState.SUPPORTED,
            supported_field_kinds=list(_DEFAULT_FIELD_SUPPORT.keys()),
            limitations=[
                "Human-assisted mode — no automated submission.",
            ],
            source="registry",
        ))

    def register(self, profile: PlatformCapability) -> None:
        """Register a platform capability profile."""
        self._profiles[profile.platform] = profile

    def get(self, platform: str) -> PlatformCapability:
        """Get capability profile for a platform.

        Falls back to generic if platform not found.
        """
        return self._profiles.get(platform, self._profiles.get(
            "generic",
            PlatformCapability(platform=platform, display_name=platform),
        ))

    def list_platforms(self) -> list[str]:
        """List all registered platform identifiers."""
        return list(self._profiles.keys())

    def has_platform(self, platform: str) -> bool:
        """Check if a platform is registered."""
        return platform in self._profiles


# ---------------------------------------------------------------------------
# Runtime capability observation
# ---------------------------------------------------------------------------

@dataclass
class RuntimeCapabilityObservation:
    """Capability observation from browser inspection.

    Used for unknown platforms to discover capabilities at runtime.
    """

    origin: str = ""
    domain: str = ""
    observed_at: str = ""
    form_fields: list[dict] = field(default_factory=list)
    has_file_input: bool = False
    has_multi_page: bool = False
    has_autocomplete: bool = False
    has_review_button: bool = False
    has_submit_button: bool = False
    has_captcha: bool = False
    has_login_form: bool = False
    navigation_elements: list[dict] = field(default_factory=list)
    confidence: str = "medium"
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.observed_at:
            self.observed_at = datetime.now(timezone.utc).isoformat()

    def to_capability(self) -> PlatformCapability:
        """Convert observation to a capability profile."""
        field_kinds = set()
        for f in self.form_fields:
            kind = f.get("kind", "text")
            field_kinds.add(kind)

        supported = []
        all_kinds = {"text", "textarea", "select", "radio", "checkbox",
                     "file", "date", "multi_select", "currency", "autocomplete"}
        for kind in all_kinds:
            if kind in field_kinds:
                supported.append(kind)
            else:
                # Not observed doesn't mean unsupported
                pass

        limitations = []
        if self.has_captcha:
            limitations.append("CAPTCHA detected — requires human intervention.")
        if self.has_login_form:
            limitations.append("Login form detected — authentication required.")

        return PlatformCapability(
            platform="discovered",
            display_name=f"Discovered: {self.domain}",
            multi_page_forms=(
                CapabilityState.SUPPORTED if self.has_multi_page
                else CapabilityState.UNKNOWN
            ),
            autocomplete=(
                CapabilityState.SUPPORTED if self.has_autocomplete
                else CapabilityState.UNKNOWN
            ),
            file_upload=(
                CapabilityState.SUPPORTED if self.has_file_input
                else CapabilityState.UNKNOWN
            ),
            captcha_detection=(
                CapabilityState.SUPPORTED if self.has_captcha
                else CapabilityState.UNKNOWN
            ),
            authentication_detection=(
                CapabilityState.SUPPORTED if self.has_login_form
                else CapabilityState.UNKNOWN
            ),
            review_page_detection=(
                CapabilityState.SUPPORTED if self.has_review_button
                else CapabilityState.UNKNOWN
            ),
            confirmation_detection=(
                CapabilityState.SUPPORTED if self.has_submit_button
                else CapabilityState.UNKNOWN
            ),
            submission_capability=(
                SubmissionCapability.SUPPORTED if self.has_submit_button
                else SubmissionCapability.UNKNOWN
            ),
            supported_field_kinds=supported,
            limitations=limitations,
            source="discovery",
            confidence=self.confidence,
        )


# ---------------------------------------------------------------------------
# Execution plan
# ---------------------------------------------------------------------------

@dataclass
class ExecutionPlan:
    """Deterministic execution plan for a specific application."""

    platform: str
    strategy: str = ExecutionStrategy.REVIEW_REQUIRED
    capability_profile: PlatformCapability | None = None

    # Capability assessment
    supported_controls: list[str] = field(default_factory=list)
    unsupported_controls: list[str] = field(default_factory=list)
    partial_controls: list[str] = field(default_factory=list)

    # Requirement match
    required_capabilities: list[str] = field(default_factory=list)
    satisfied_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)

    # Safety
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_human_steps: list[str] = field(default_factory=list)

    # Confidence
    estimated_confidence: float = 0.0
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_executable(self) -> bool:
        """Whether this plan allows execution."""
        return self.strategy in (
            ExecutionStrategy.FULL_AUTOMATIC,
            ExecutionStrategy.GUIDED_AUTOMATIC,
            ExecutionStrategy.HUMAN_ASSISTED,
        )

    @property
    def has_blockers(self) -> bool:
        return len(self.blockers) > 0

    @property
    def needs_review(self) -> bool:
        return self.strategy == ExecutionStrategy.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Execution requirement
# ---------------------------------------------------------------------------

@dataclass
class ExecutionRequirement:
    """A specific capability required for execution."""

    name: str
    required: bool = True
    capability_state: str = CapabilityState.UNKNOWN
    reason: str = ""


# ---------------------------------------------------------------------------
# Planning functions
# ---------------------------------------------------------------------------

def evaluate_capability_match(
    platform_cap: PlatformCapability,
    required_capabilities: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Evaluate which required capabilities are satisfied.

    Returns (satisfied, missing, partial).
    """
    satisfied: list[str] = []
    missing: list[str] = []
    partial: list[str] = []

    capability_map = _build_capability_map(platform_cap)

    for cap_name in required_capabilities:
        state = capability_map.get(cap_name, CapabilityState.UNKNOWN)
        if state == CapabilityState.SUPPORTED:
            satisfied.append(cap_name)
        elif state == CapabilityState.PARTIAL:
            partial.append(cap_name)
        else:
            missing.append(cap_name)

    return satisfied, missing, partial


def _build_capability_map(cap: PlatformCapability) -> dict[str, str]:
    """Build a flat capability name → state map.

    Normalizes SubmissionCapability to CapabilityState for uniform comparison.
    """
    submission_state_map = {
        SubmissionCapability.SUPPORTED: CapabilityState.SUPPORTED,
        SubmissionCapability.PARTIAL: CapabilityState.PARTIAL,
        SubmissionCapability.UNSUPPORTED: CapabilityState.UNSUPPORTED,
        SubmissionCapability.UNKNOWN: CapabilityState.UNKNOWN,
    }
    return {
        "multi_page_forms": cap.multi_page_forms,
        "conditional_fields": cap.conditional_fields,
        "autocomplete": cap.autocomplete,
        "file_upload": cap.file_upload,
        "multiple_file_upload": cap.multiple_file_upload,
        "authentication_detection": cap.authentication_detection,
        "mfa_detection": cap.mfa_detection,
        "captcha_detection": cap.captcha_detection,
        "review_page_detection": cap.review_page_detection,
        "confirmation_detection": cap.confirmation_detection,
        "reference_id_extraction": cap.reference_id_extraction,
        "submission": submission_state_map.get(
            cap.submission_capability, CapabilityState.UNKNOWN
        ),
        "duplicate_detection": cap.duplicate_detection_support,
    }


def determine_strategy(
    platform_cap: PlatformCapability,
    satisfied: list[str],
    missing: list[str],
    partial: list[str],
    auth_state: str | None = None,
    captcha_detected: bool = False,
) -> tuple[str, list[str], list[str]]:
    """Determine execution strategy from capability assessment.

    Returns (strategy, blockers, warnings).
    """
    blockers: list[str] = []
    warnings: list[str] = []

    # CAPTCHA → always blocked
    if captcha_detected:
        return ExecutionStrategy.BLOCKED, ["CAPTCHA detected."], []

    # Auth requires human → pause
    if auth_state in ("LOGIN_REQUIRED", "MFA_REQUIRED", "CAPTCHA_REQUIRED"):
        return ExecutionStrategy.HUMAN_ASSISTED, [], [
            f"Authentication state: {auth_state}."
        ]

    # Auth terminal → blocked
    if auth_state in ("AUTH_FAILED", "SESSION_EXPIRED", "BLOCKED"):
        return ExecutionStrategy.BLOCKED, [f"Auth terminal: {auth_state}."], []

    # Submission unknown → review
    if platform_cap.submission_capability == SubmissionCapability.UNKNOWN:
        warnings.append("Submission capability unknown.")

    # Required capabilities missing → blocked (except submission which has special handling)
    non_submission_missing = [c for c in missing if c != "submission"]
    if non_submission_missing:
        blockers.extend(
            f"Required capability '{c}' is MISSING." for c in non_submission_missing
        )
        return ExecutionStrategy.BLOCKED, blockers, warnings

    # Submission missing/unknown → review (not block)
    if "submission" in missing:
        warnings.append("Submission capability is UNKNOWN/MISSING.")

    # Partial capabilities → warning (not block) unless critical
    critical_partial = {"submission", "file_upload", "multi_page_forms"}
    critical_partials = [c for c in partial if c in critical_partial]
    non_critical_partials = [c for c in partial if c not in critical_partial]

    if critical_partials:
        warnings.extend(f"Critical capability '{c}' is PARTIAL." for c in critical_partials)
        return ExecutionStrategy.REVIEW_REQUIRED, [], warnings

    if non_critical_partials:
        warnings.extend(f"Capability '{c}' is PARTIAL." for c in non_critical_partials)

    # All satisfied → check submission capability
    if platform_cap.submission_capability == SubmissionCapability.SUPPORTED:
        return ExecutionStrategy.FULL_AUTOMATIC, [], warnings
    elif platform_cap.submission_capability == SubmissionCapability.PARTIAL:
        return ExecutionStrategy.GUIDED_AUTOMATIC, [], warnings
    elif platform_cap.submission_capability == SubmissionCapability.UNSUPPORTED:
        return ExecutionStrategy.HUMAN_ASSISTED, [], warnings
    else:
        return ExecutionStrategy.REVIEW_REQUIRED, [], warnings


def generate_execution_plan(
    *,
    platform: str,
    required_capabilities: list[str] | None = None,
    auth_state: str | None = None,
    captcha_detected: bool = False,
    registry: PlatformCapabilityRegistry | None = None,
) -> ExecutionPlan:
    """Generate a deterministic execution plan for a platform.

    This is the main entry point for execution planning.
    """
    if registry is None:
        registry = PlatformCapabilityRegistry()

    platform_cap = registry.get(platform)

    if required_capabilities is None:
        required_capabilities = [
            "multi_page_forms",
            "file_upload",
            "authentication_detection",
            "captcha_detection",
            "review_page_detection",
            "confirmation_detection",
            "submission",
        ]

    satisfied, missing, partial = evaluate_capability_match(
        platform_cap, required_capabilities
    )

    strategy, blockers, warnings = determine_strategy(
        platform_cap, satisfied, missing, partial,
        auth_state=auth_state,
        captcha_detected=captcha_detected,
    )

    # Build supported/unsupported control lists
    cap_map = _build_capability_map(platform_cap)
    supported_controls = [
        k for k, v in cap_map.items()
        if v == CapabilityState.SUPPORTED
    ]
    unsupported_controls = [
        k for k, v in cap_map.items()
        if v == CapabilityState.UNSUPPORTED
    ]
    partial_controls = [
        k for k, v in cap_map.items()
        if v == CapabilityState.PARTIAL
    ]

    # Required human steps
    human_steps: list[str] = []
    if auth_state in ("LOGIN_REQUIRED", "MFA_REQUIRED"):
        human_steps.append("User must complete authentication.")
    if captcha_detected:
        human_steps.append("User must solve CAPTCHA.")

    # Confidence
    confidence = 1.0
    if missing:
        confidence -= 0.3 * len(missing)
    if partial:
        confidence -= 0.1 * len(partial)
    if warnings:
        confidence -= 0.05 * len(warnings)
    confidence = max(0.0, min(1.0, confidence))

    return ExecutionPlan(
        platform=platform,
        strategy=strategy,
        capability_profile=platform_cap,
        supported_controls=supported_controls,
        unsupported_controls=unsupported_controls,
        partial_controls=partial_controls,
        required_capabilities=required_capabilities,
        satisfied_capabilities=satisfied,
        missing_capabilities=missing,
        blockers=blockers,
        warnings=warnings,
        required_human_steps=human_steps,
        estimated_confidence=round(confidence, 2),
    )


# ---------------------------------------------------------------------------
# Capability discovery for unknown platforms
# ---------------------------------------------------------------------------

def discover_capabilities_from_observation(
    observation: RuntimeCapabilityObservation,
) -> PlatformCapability:
    """Convert a runtime observation to a capability profile.

    Used for unknown platforms discovered during execution.
    """
    return observation.to_capability()


# ---------------------------------------------------------------------------
# Platform support decision
# ---------------------------------------------------------------------------

def decide_platform_support(
    plan: ExecutionPlan,
) -> tuple[str, list[str]]:
    """Make a final platform support decision from an execution plan.

    Returns (decision, reasons).
    Decision is one of: READY_FOR_EXECUTION, REVIEW, BLOCKED
    """
    reasons: list[str] = []

    if plan.has_blockers:
        reasons.extend(plan.blockers)
        return "BLOCKED", reasons

    if plan.strategy == ExecutionStrategy.BLOCKED:
        reasons.append("Strategy is BLOCKED.")
        return "BLOCKED", reasons

    if plan.strategy == ExecutionStrategy.REVIEW_REQUIRED:
        reasons.extend(plan.warnings)
        return "REVIEW", reasons

    if plan.strategy in (
        ExecutionStrategy.FULL_AUTOMATIC,
        ExecutionStrategy.GUIDED_AUTOMATIC,
        ExecutionStrategy.HUMAN_ASSISTED,
    ):
        if plan.warnings:
            reasons.extend(plan.warnings)
        return "READY_FOR_EXECUTION", reasons

    return "REVIEW", ["Unknown strategy."]


# ---------------------------------------------------------------------------
# Singleton registry instance
# ---------------------------------------------------------------------------

_default_registry: PlatformCapabilityRegistry | None = None


def get_capability_registry() -> PlatformCapabilityRegistry:
    """Get the default capability registry singleton."""
    global _default_registry
    if _default_registry is None:
        _default_registry = PlatformCapabilityRegistry()
    return _default_registry
