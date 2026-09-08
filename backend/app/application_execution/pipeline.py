"""Mapping pipeline and form validation (Phase 12).

Implements the full mapping pipeline: INSPECT → EXTRACT → NORMALIZE → MATCH →
LOOKUP → CALCULATE → APPLY → VALIDATE. Also handles required field validation
and contradiction detection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.application_execution import base
from app.application_execution.field_catalog import (
    SENSITIVITY_HIGH,
    SENSITIVITY_LOW,
    SENSITIVITY_MEDIUM,
)
from app.application_execution.memory import MemoryStore
from app.application_execution.semantic_mapper import (
    FieldMapping,
    map_fields_semantic,
)

# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
STAGE_INSPECT = "INSPECT"
STAGE_EXTRACT = "EXTRACT"
STAGE_NORMALIZE = "NORMALIZE"
STAGE_MATCH = "MATCH"
STAGE_LOOKUP = "LOOKUP"
STAGE_CALCULATE = "CALCULATE"
STAGE_APPLY = "APPLY"
STAGE_VALIDATE = "VALIDATE"

ALL_STAGES = [
    STAGE_INSPECT, STAGE_EXTRACT, STAGE_NORMALIZE, STAGE_MATCH,
    STAGE_LOOKUP, STAGE_CALCULATE, STAGE_APPLY, STAGE_VALIDATE,
]


@dataclass
class PipelineField:
    """A field that has gone through the mapping pipeline."""

    # Stage: INSPECT
    raw_label: str = ""
    raw_type: str = "text"
    raw_value: str | None = None
    raw_options: list[str] = field(default_factory=list)
    raw_required: bool = False

    # Stage: EXTRACT
    extracted_label: str = ""

    # Stage: NORMALIZE
    normalized_label: str = ""

    # Stage: MATCH
    mapping: FieldMapping | None = None

    # Stage: LOOKUP
    profile_value: str | None = None
    memory_value: str | None = None

    # Stage: CALCULATE
    calculated_value: str | None = None
    calculated_source: str = ""

    # Stage: APPLY
    final_value: str | None = None
    apply_method: str = ""  # auto | manual | skip

    # Stage: VALIDATE
    valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Result of the full mapping pipeline."""

    fields: list[PipelineField] = field(default_factory=list)
    stages_completed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ready_fields(self) -> int:
        return len([f for f in self.fields if f.valid and f.final_value is not None])

    @property
    def blocked_fields(self) -> int:
        return len([f for f in self.fields if not f.valid or f.validation_errors])

    @property
    def needs_review_fields(self) -> list[PipelineField]:
        return [
            f for f in self.fields
            if f.mapping and f.mapping.sensitivity in (SENSITIVITY_MEDIUM, SENSITIVITY_HIGH)
        ]


# ---------------------------------------------------------------------------
# Pipeline implementation
# ---------------------------------------------------------------------------

def run_pipeline(
    detected: list[base.DetectedField],
    profile: dict | None = None,
    memory: MemoryStore | None = None,
    user_verified_mappings: dict[str, str] | None = None,
) -> PipelineResult:
    """Run the full mapping pipeline on detected fields.

    Pipeline stages:
    1. INSPECT: Extract raw field data
    2. EXTRACT: Parse label text
    3. NORMALIZE: Normalize label format
    4. MATCH: Map to canonical concept
    5. LOOKUP: Find values in profile/memory
    6. CALCULATE: Compute derived values if needed
    7. APPLY: Determine how to fill (auto/manual/skip)
    8. VALIDATE: Check required, type, consistency
    """
    profile = profile or {}
    memory = memory or MemoryStore()
    result = PipelineResult()

    # Stage 1-3: Inspect, extract, normalize
    pipeline_fields = []
    for raw in detected:
        pf = PipelineField(
            raw_label=raw.label or "",
            raw_type=raw.kind or "text",
            raw_value=raw.value,
            raw_options=[],
            raw_required=raw.required if hasattr(raw, "required") else False,
            extracted_label=raw.label or "",
            normalized_label=_normalize_label(raw.label or ""),
        )
        pipeline_fields.append(pf)

    result.stages_completed.append(STAGE_INSPECT)
    result.stages_completed.append(STAGE_EXTRACT)
    result.stages_completed.append(STAGE_NORMALIZE)

    # Stage 4: Match (semantic mapping)
    mapping_result = map_fields_semantic(detected, user_verified_mappings)
    for i, pf in enumerate(pipeline_fields):
        if i < len(mapping_result.mappings):
            pf.mapping = mapping_result.mappings[i]

    result.warnings.extend(mapping_result.warnings)
    result.stages_completed.append(STAGE_MATCH)

    # Stage 5: Lookup (profile and memory)
    for pf in pipeline_fields:
        if pf.mapping and pf.mapping.canonical:
            # Try profile lookup
            pf.profile_value = _lookup_profile(
                pf.mapping.canonical, profile
            )
            # Try memory lookup
            if pf.raw_label:
                answer = memory.get_answer(pf.raw_label)
                if answer:
                    pf.memory_value = answer.answer

    result.stages_completed.append(STAGE_LOOKUP)

    # Stage 6: Calculate (derived values)
    for pf in pipeline_fields:
        if pf.profile_value:
            pf.calculated_value = pf.profile_value
            pf.calculated_source = "profile"
        elif pf.memory_value:
            pf.calculated_value = pf.memory_value
            pf.calculated_source = "memory"
        elif pf.mapping and pf.mapping.canonical:
            derived = _calculate_derived(pf.mapping.canonical, profile)
            if derived:
                pf.calculated_value = derived
                pf.calculated_source = "derived"

    result.stages_completed.append(STAGE_CALCULATE)

    # Stage 7: Apply (determine fill method)
    for pf in pipeline_fields:
        if pf.calculated_value:
            sensitivity = SENSITIVITY_LOW
            if pf.mapping:
                sensitivity = pf.mapping.sensitivity

            if sensitivity == SENSITIVITY_LOW:
                pf.apply_method = "auto"
                pf.final_value = pf.calculated_value
            elif sensitivity == SENSITIVITY_MEDIUM:
                pf.apply_method = "manual"
                pf.final_value = pf.calculated_value
                result.warnings.append(
                    f"Medium-sensitivity field '{pf.raw_label}' needs user confirmation."
                )
            elif sensitivity == SENSITIVITY_HIGH:
                pf.apply_method = "skip"
                result.warnings.append(
                    f"High-sensitivity field '{pf.raw_label}' requires explicit user verification."
                )
        else:
            pf.apply_method = "manual"

    result.stages_completed.append(STAGE_APPLY)

    # Stage 8: Validate
    for pf in pipeline_fields:
        errors, warnings = _validate_field(pf)
        pf.validation_errors = errors
        pf.validation_warnings = warnings
        pf.valid = len(errors) == 0

    result.stages_completed.append(STAGE_VALIDATE)
    result.fields = pipeline_fields

    return result


def _normalize_label(label: str) -> str:
    """Normalize a field label."""
    normalized = label.lower().strip()
    normalized = re.sub(r"[*:?\-()]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _lookup_profile(canonical: str, profile: dict) -> str | None:
    """Look up a canonical field in the profile."""
    PROFILE_KEY_MAP = {
        "FIRST_NAME": ["first_name", "firstName"],
        "LAST_NAME": ["last_name", "lastName"],
        "FULL_NAME": ["full_name", "fullName", "name"],
        "EMAIL": ["email"],
        "PHONE": ["phone", "phone_number"],
        "LOCATION": ["location", "city"],
        "STATE": ["state", "province"],
        "COUNTRY": ["country"],
        "ADDRESS": ["address", "street_address"],
        "LINKEDIN_URL": ["linkedin_url", "linkedin"],
        "GITHUB_URL": ["github_url", "github"],
        "PORTFOLIO_URL": ["portfolio_url", "website"],
        "CURRENT_COMPANY": ["company", "current_company"],
        "YEARS_EXPERIENCE": ["years_experience", "experience_years"],
        "CURRENT_ROLE": ["role", "current_role", "title", "current_title"],
        "NOTICE_PERIOD": ["notice_period"],
        "SALARY_EXPECTATION": ["salary_expectation", "expected_salary"],
        "CURRENT_CTC": ["current_ctc", "current_salary"],
        "DEGREE": ["degree", "education"],
        "UNIVERSITY": ["university", "college"],
        "GRADUATION_YEAR": ["graduation_year"],
        "WORK_AUTHORIZATION": ["work_authorization", "authorization"],
        "SPONSORSHIP_REQUIRED": ["sponsorship_required"],
    }

    keys = PROFILE_KEY_MAP.get(canonical, [])
    for key in keys:
        value = profile.get(key)
        if value is not None:
            return str(value)
    return None


def _calculate_derived(canonical: str, profile: dict) -> str | None:
    """Calculate derived values from profile data."""
    if canonical == "FULL_NAME":
        first = profile.get("first_name", "")
        last = profile.get("last_name", "")
        if first and last:
            return f"{first} {last}"
        return first or last or None

    return None


def _validate_field(pf: PipelineField) -> tuple[list[str], list[str]]:
    """Validate a pipeline field. Returns (errors, warnings)."""
    errors = []
    warnings = []

    # Check required fields
    if pf.raw_required and not pf.final_value:
        errors.append(f"Required field '{pf.raw_label}' has no value.")

    # Validate email
    if pf.mapping and pf.mapping.canonical == "EMAIL" and pf.final_value:
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", pf.final_value):
            errors.append(f"Invalid email format: '{pf.final_value}'")

    # Validate URL
    if pf.mapping and pf.mapping.canonical in ("LINKEDIN_URL", "GITHUB_URL", "PORTFOLIO_URL"):
        if pf.final_value and not pf.final_value.startswith(("http://", "https://")):
            warnings.append(f"URL should start with http:// or https://: '{pf.final_value}'")

    # Validate year
    if pf.mapping and pf.mapping.canonical in ("GRADUATION_YEAR",):
        if pf.final_value:
            try:
                year = int(pf.final_value)
                if year < 1900 or year > 2100:
                    errors.append(f"Invalid graduation year: {year}")
            except ValueError:
                errors.append(f"Graduation year must be a number: '{pf.final_value}'")

    return errors, warnings


# ---------------------------------------------------------------------------
# Contradiction detection
# ---------------------------------------------------------------------------

@dataclass
class Contradiction:
    """A contradiction detected between two fields."""

    field1: str
    value1: str
    field2: str
    value2: str
    reason: str
    severity: str = "WARNING"  # WARNING | ERROR


def detect_contradictions(
    fields: list[PipelineField],
) -> list[Contradiction]:
    """Detect contradictions between field values."""
    contradictions = []

    # Build value map
    value_map: dict[str, str] = {}
    for pf in fields:
        if pf.mapping and pf.final_value:
            value_map[pf.mapping.canonical] = pf.final_value

    # Check email consistency
    if "EMAIL" in value_map:
        email = value_map["EMAIL"]
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            contradictions.append(Contradiction(
                field1="EMAIL",
                value1=email,
                field2="FORMAT",
                value2="expected",
                reason="Email format is invalid.",
                severity="ERROR",
            ))

    # Check name consistency
    if "FULL_NAME" in value_map and "FIRST_NAME" in value_map:
        full_name = value_map["FULL_NAME"]
        first_name = value_map["FIRST_NAME"]
        if first_name.lower() not in full_name.lower():
            contradictions.append(Contradiction(
                field1="FULL_NAME",
                value1=full_name,
                field2="FIRST_NAME",
                value2=first_name,
                reason="First name does not appear in full name.",
                severity="WARNING",
            ))

    # Check salary logic
    if "CURRENT_CTC" in value_map and "SALARY_EXPECTATION" in value_map:
        try:
            current = float(re.sub(r"[^\d.]", "", value_map["CURRENT_CTC"]))
            expected = float(re.sub(r"[^\d.]", "", value_map["SALARY_EXPECTATION"]))
            if expected < current * 0.5:
                contradictions.append(Contradiction(
                    field1="CURRENT_CTC",
                    value1=value_map["CURRENT_CTC"],
                    field2="SALARY_EXPECTATION",
                    value2=value_map["SALARY_EXPECTATION"],
                    reason="Expected salary is less than 50% of current salary.",
                    severity="WARNING",
                ))
        except (ValueError, TypeError):
            pass

    return contradictions
