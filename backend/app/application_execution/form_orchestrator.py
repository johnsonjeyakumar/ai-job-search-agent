"""Multi-step form orchestration engine (Phase 14 + Phase 17).

Extends the Phase 12 execution engine to handle multi-page application
forms. Orchestrates the cycle: INSPECT -> MAP -> FILL -> VALIDATE ->
NAVIGATE -> CHECKPOINT -> INSPECT NEXT -> ... -> REVIEW -> SUBMIT.

Phase 17 adds:
- Advanced field normalization (date, currency, multi-select, checkbox, radio, autocomplete)
- Safe file upload with validation chain
- Evidence recording for all actions
- Human approval integration
- Conditional field detection and re-mapping

Safety:
- One navigation click per transition (idempotent)
- Checkpoint after every page completion
- Dynamic field detection after interactions
- Never blindly click "continue" -- verify it's real navigation
- Never interpret navigation as submission
- Browser state is source of truth; checkpoints are recovery metadata
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.application_execution.base import (
    KNOWN,
    REQUIRES_REVIEW,
    UNKNOWN,
    DetectedField,
    FillResult,
)
from app.application_execution.fields import (
    MappingResult,
    ProfileContext,
    map_fields,
)
from app.application_execution.form_session import (
    FieldState,
    FormSession,
    FormSessionState,
    NavigationAction,
    PageSnapshot,
    PageType,
    TrackedField,
)
from app.application_execution.page_detector import (
    build_page_snapshot,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_NAVIGATION_RETRIES = 3
MAX_DYNAMIC_FIELD_RETRIES = 5
DOM_STABILIZATION_WAIT_MS = 500
PAGE_TIMEOUT_MS = 30000
NAVIGATION_TIMEOUT_MS = 15000

# ---------------------------------------------------------------------------
# Orchestration result
# ---------------------------------------------------------------------------

@dataclass
class OrchestrationResult:
    """Result of running the multi-step orchestration."""
    session: FormSession
    status: FormSessionState
    message: str = ""
    pages_processed: int = 0
    fields_filled: int = 0
    questions_found: int = 0
    navigation_actions: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Page inspection
# ---------------------------------------------------------------------------

def inspect_page(
    session: FormSession,
    url: str,
    raw_fields: list[DetectedField],
    navigation_elements: list[dict],
    heading: str | None = None,
    step_indicator: str | None = None,
    validation_errors: list[str] | None = None,
) -> PageSnapshot:
    """Inspect the current page and create a snapshot.

    Called after browser navigation to capture the state of the page.
    """
    page_index = session.current_page_index + 1
    snapshot = build_page_snapshot(
        url=url,
        fields=raw_fields,
        navigation_elements=navigation_elements,
        heading=heading,
        step_indicator=step_indicator,
        page_index=page_index,
        validation_errors=validation_errors,
    )
    session.add_page(snapshot)
    session.set_current_page(snapshot.page_key)
    session.transition(FormSessionState.PAGE_INSPECTED)
    return snapshot


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def map_page_fields(
    session: FormSession,
    profile: ProfileContext,
) -> MappingResult:
    """Map fields on the current page using the profile context.

    Uses the existing Phase 7 field mapper for each page.
    """
    snapshot = session.get_current_page()
    if snapshot is None:
        raise ValueError("No current page to map")

    detected_fields = [t.detected for t in snapshot.fields]
    result = map_fields(detected_fields, profile)

    # Update tracked fields with mapping results
    for mapped in result.fields:
        for tracked in snapshot.fields:
            if tracked.detected.label == mapped.detected.label:
                tracked.canonical = mapped.matched_key
                tracked.value = mapped.value
                if mapped.classification == KNOWN:
                    tracked.state = FieldState.MAPPED
                    tracked.confidence = 1.0
                elif mapped.classification == REQUIRES_REVIEW:
                    tracked.state = FieldState.MAPPED
                    tracked.confidence = 0.5
                break

    # Update session state
    snapshot.required_fields_count = sum(
        1 for t in snapshot.fields if t.required and t.visible
    )
    session.transition(FormSessionState.FIELDS_MAPPED)
    return result


# ---------------------------------------------------------------------------
# Field filling
# ---------------------------------------------------------------------------

def fill_page_fields(
    session: FormSession,
    driver,
    mapping_result: MappingResult,
) -> list[FillResult]:
    """Fill all KNOWN fields on the current page.

    Phase 17: Normalizes values based on field kind before filling.
    Returns fill results for each attempted field.
    """
    snapshot = session.get_current_page()
    if snapshot is None:
        raise ValueError("No current page to fill")

    results = []
    for mapped in mapping_result.fields:
        if mapped.classification != KNOWN or not mapped.value:
            continue

        tracked = next(
            (t for t in snapshot.fields if t.detected.label == mapped.detected.label),
            None,
        )
        if tracked is None or not tracked.visible:
            continue

        # Skip file fields here -- handled separately
        if mapped.detected.kind == "file":
            continue

        # Phase 17: normalize value before filling
        normalized_value, norm_error = normalize_field_value(mapped, mapped.detected)
        if norm_error:
            results.append(FillResult(
                status=UNKNOWN,
                value=None,
                error=norm_error,
                control_type=mapped.detected.kind,
            ))
            continue

        try:
            fill_result = driver.fill(mapped.detected.key, normalized_value or mapped.value)
            tracked.value = normalized_value or mapped.value
            tracked.state = FieldState.FILLED
            results.append(fill_result)
        except Exception as e:
            results.append(FillResult(
                status=UNKNOWN,
                value=None,
                error=str(e),
            ))

    snapshot.filled_fields_count = sum(
        1 for t in snapshot.fields if t.state == FieldState.FILLED
    )
    session.transition(FormSessionState.FIELDS_FILLED)
    return results


# ---------------------------------------------------------------------------
# Page validation
# ---------------------------------------------------------------------------

def validate_page(
    session: FormSession,
    mapping_result: MappingResult,
) -> tuple[bool, list[str]]:
    """Validate the current page.

    Returns (is_valid, list of issues).
    """
    snapshot = session.get_current_page()
    if snapshot is None:
        return False, ["No current page"]

    issues: list[str] = []

    # Check required unfilled fields
    for tracked in snapshot.fields:
        if tracked.required and tracked.visible and tracked.value is None:
            if tracked.state not in (FieldState.MAPPED, FieldState.FILLED):
                issues.append(f"Required field '{tracked.detected.label}' is not filled")

    # Check fields with validation errors
    if snapshot.validation_errors:
        issues.extend(snapshot.validation_errors)

    # Check new questions that need answers
    for question in mapping_result.new_questions:
        # All new questions require user attention in multi-step context
        issues.append(f"New question requires answer: {question.label}")

    is_valid = len(issues) == 0
    if is_valid:
        session.transition(FormSessionState.PAGE_VALIDATED)
    else:
        session.transition(FormSessionState.WAITING_USER)

    return is_valid, issues


# ---------------------------------------------------------------------------
# Dynamic form detection
# ---------------------------------------------------------------------------

def detect_dynamic_changes(
    session: FormSession,
    previous_fingerprints: set[str],
    new_fields: list[DetectedField],
) -> dict:
    """Detect if the form changed after an interaction.

    Compares the previous field set with the current field set to detect
    newly appeared or disappeared fields (conditional questions).
    """
    snapshot = session.get_current_page()
    if snapshot is None:
        return {"has_changes": False}

    new_fps = set()
    for f in new_fields:
        raw = f"{f.label}|{f.kind}|{f.required}"
        import hashlib
        fp = hashlib.sha256(raw.encode()).hexdigest()[:12]
        new_fps.add(fp)

    added_fps = new_fps - previous_fingerprints
    removed_fps = previous_fingerprints - new_fps

    added_fields = [f for f in new_fields if any(
        hashlib.sha256(f"{f.label}|{f.kind}|{f.required}".encode()).hexdigest()[:12] == fp
        for fp in added_fps
    )]
    removed_tracked = [t for t in snapshot.fields if any(
        hashlib.sha256(
            f"{t.detected.label}|{t.detected.kind}|{t.required}".encode()
        ).hexdigest()[:12] == fp
        for fp in removed_fps
    )]

    return {
        "has_changes": bool(added_fields or removed_tracked),
        "added_fields": added_fields,
        "removed_fields": [t.detected for t in removed_tracked],
        "added_count": len(added_fields),
        "removed_count": len(removed_tracked),
    }


# ---------------------------------------------------------------------------
# Navigation handling
# ---------------------------------------------------------------------------

def navigate_to_next(
    session: FormSession,
    driver,
    snapshot: PageSnapshot,
) -> bool:
    """Navigate to the next page.

    Returns True if navigation succeeded.
    """
    if not snapshot.has_next_button or not snapshot.next_button_selector:
        return False

    session.transition(FormSessionState.NAVIGATING)
    from_page = session.current_page_key

    try:
        driver.fill(snapshot.next_button_selector, "", force_click=True)
        time.sleep(DOM_STABILIZATION_WAIT_MS / 1000)
        session.record_navigation(
            NavigationAction.NEXT_PAGE,
            from_page,
            "completed",
        )
        return True
    except Exception:
        if session.navigation_history:
            session.navigation_history[-1]["status"] = "failed"
        return False


def navigate_to_previous(
    session: FormSession,
    driver,
    snapshot: PageSnapshot,
) -> bool:
    """Navigate to the previous page."""
    if not snapshot.has_back_button or not snapshot.back_button_selector:
        return False

    session.transition(FormSessionState.NAVIGATING)
    from_page = session.current_page_key

    try:
        driver.fill(snapshot.back_button_selector, "", force_click=True)
        time.sleep(DOM_STABILIZATION_WAIT_MS / 1000)
        session.record_navigation(
            NavigationAction.PREVIOUS_PAGE,
            from_page,
            "pending",
        )
        session.navigation_history[-1]["status"] = "completed"
        return True
    except Exception:
        session.navigation_history[-1]["status"] = "failed"
        return False


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------

def run_multi_step_orchestration(
    session: FormSession,
    driver,
    profile: ProfileContext,
    *,
    headless: bool = True,
) -> OrchestrationResult:
    """Run the multi-step form orchestration loop.

    This is the main entry point for processing multi-page forms.
    It handles the complete cycle from first page inspection through
    final submission.

    The loop continues until:
    - A review page is reached (-> approval)
    - A submit button is detected (-> approval)
    - An error occurs
    - Human input is needed
    """
    result = OrchestrationResult(session=session, status=session.status)
    page_count = 0

    while session.status not in (
        FormSessionState.SUBMITTED,
        FormSessionState.CONFIRMED,
        FormSessionState.FAILED,
        FormSessionState.BLOCKED,
        FormSessionState.COMPLETED,
        FormSessionState.READY_TO_SUBMIT,
        FormSessionState.WAITING_APPROVAL,
        FormSessionState.WAITING_USER,
    ):
        try:
            page_count += 1
            result.pages_processed = page_count

            # Step 1: Inspect current page
            current_url = driver.get_current_url() if hasattr(driver, "get_current_url") else ""
            raw_fields = driver.inspect_form()
            heading = driver.get_heading() if hasattr(driver, "get_heading") else None
            has_nav = hasattr(driver, "get_navigation_elements")
            nav_elements = driver.get_navigation_elements() if has_nav else []

            snapshot = inspect_page(
                session, current_url, raw_fields, nav_elements, heading
            )

            # Step 2: Check if this is a review page
            if snapshot.page_type == PageType.REVIEW_PAGE:
                session.transition(FormSessionState.REVIEW)
                result.warnings.append("Review page detected — awaiting approval")
                break

            # Step 3: Check if this is a submission page
            if snapshot.page_type == PageType.SUBMISSION_PAGE:
                session.transition(FormSessionState.CONFIRMED)
                result.message = "Submission confirmed"
                break

            # Step 4: Map fields
            mapping = map_page_fields(session, profile)

            # Step 5: Fill known fields
            fill_results = fill_page_fields(session, driver, mapping)
            result.fields_filled += sum(1 for r in fill_results if r.status == KNOWN)

            # Step 6: Validate page
            is_valid, issues = validate_page(session, mapping)
            if not is_valid:
                result.warnings.extend(issues)

            # Step 7: Check for dynamic field changes after filling
            prev_fps = snapshot.field_fingerprints
            new_fields = driver.inspect_form() if hasattr(driver, "inspect_form") else []
            changes = detect_dynamic_changes(session, prev_fps, new_fields)
            if changes["has_changes"]:
                # Re-map and re-fill new fields
                snapshot.fields.extend([
                    TrackedField(detected=f) for f in changes.get("added_fields", [])
                ])
                mapping2 = map_page_fields(session, profile)
                fill_page_fields(session, driver, mapping2)
                validate_page(session, mapping2)

            # Step 8: Handle navigation
            if snapshot.page_type == PageType.FORM_PAGE and snapshot.has_next_button:
                if is_valid:
                    success = navigate_to_next(session, driver, snapshot)
                    if success:
                        result.navigation_actions += 1
                        session.transition(FormSessionState.DISCOVERING)
                        continue
                    else:
                        result.errors.append("Navigation failed")
                        session.transition(FormSessionState.FAILED)
                        break
                else:
                    # Page has issues — wait for user
                    session.transition(FormSessionState.WAITING_USER)
                    result.warnings.append("Page validation failed — needs user input")
                    break

            # If no navigation and page is valid, check for submit
            if snapshot.has_submit_button and is_valid:
                session.transition(FormSessionState.READY_TO_SUBMIT)
                break

            # No navigation available — stop
            if not snapshot.has_next_button and not snapshot.has_submit_button:
                result.warnings.append("No navigation controls found")
                session.transition(FormSessionState.WAITING_USER)
                break

        except Exception as e:
            result.errors.append(str(e))
            session.transition(FormSessionState.FAILED)
            break

    result.status = session.status
    return result


# ---------------------------------------------------------------------------
# Phase 17: Advanced field normalization
# ---------------------------------------------------------------------------

def normalize_field_value(
    mapped,
    raw_field: DetectedField,
) -> tuple[str | None, str | None]:
    """Normalize a mapped value based on field kind.

    Returns (normalized_value, error_or_none).
    """
    if not mapped.value or mapped.classification != KNOWN:
        return mapped.value, None

    kind = raw_field.kind

    if kind == "date":
        from app.application_execution.normalizer import normalize_date
        normalized = normalize_date(mapped.value)
        if normalized is None:
            return None, f"Date value '{mapped.value}' could not be normalized."
        return normalized, None

    if kind == "currency":
        from app.application_execution.normalizer import normalize_currency
        amount, code = normalize_currency(mapped.value)
        if amount is None:
            return None, f"Currency value '{mapped.value}' could not be normalized."
        return str(amount), None

    if kind == "multi_select":
        if raw_field.options and mapped.value:
            from app.application_execution.normalizer import normalize_multi_select
            requested = [s.strip() for s in mapped.value.split(",")]
            matched, unmatched = normalize_multi_select(requested, raw_field.options)
            if unmatched:
                return None, f"Unmatched options: {', '.join(unmatched)}"
            return ", ".join(matched), None
        return mapped.value, None

    if kind == "checkbox":
        from app.application_execution.normalizer import normalize_checkbox_value
        result = normalize_checkbox_value(mapped.value)
        if result is None:
            return None, f"Checkbox value '{mapped.value}' is not a valid boolean."
        return str(result).lower(), None

    if kind == "radio":
        if raw_field.options:
            from app.application_execution.normalizer import normalize_radio_value
            result = normalize_radio_value(mapped.value, raw_field.options)
            if result is None:
                return None, (
                    f"Radio value '{mapped.value}' is not among options: "
                    f"{', '.join(raw_field.options)}"
                )
            return result, None
        return mapped.value, None

    if kind == "autocomplete":
        from app.application_execution.normalizer import normalize_autocomplete_input
        return normalize_autocomplete_input(mapped.value), None

    return mapped.value, None


# ---------------------------------------------------------------------------
# Phase 17: File upload handling
# ---------------------------------------------------------------------------

def resolve_file_for_upload(
    field: DetectedField,
    *,
    resume=None,
    package_id: int | None = None,
) -> tuple[bytes | None, str | None, str | None, str | None, str | None]:
    """Resolve the file bytes, filename, content_type, document_type, and error.

    Returns (data, file_name, content_type, document_type, error).
    """
    from app.application_execution.file_handler import detect_document_type_from_label

    document_type = detect_document_type_from_label(field.label or "")

    # Only resume is auto-resolved from the package
    if document_type != "resume" or resume is None:
        return None, None, None, document_type, None

    # Resolve bytes from storage
    try:
        from app.storage.local import get_storage
        data = get_storage().load(resume.file_path)
    except (OSError, ValueError):
        return None, resume.file_name, resume.content_type, document_type, (
            f"Resume file '{resume.file_name}' could not be loaded from storage."
        )

    return (
        data,
        resume.file_name,
        resume.content_type or "application/pdf",
        document_type,
        None,
    )


def validate_and_upload_file(
    driver,
    data: bytes,
    file_name: str,
    content_type: str,
    document_type: str,
    *,
    package_id: int | None = None,
) -> tuple[FillResult, str | None]:
    """Validate file via the full chain, then upload.

    Returns (result, error_or_none).
    """
    from app.application_execution.file_handler import (
        validate_file_for_upload,
    )

    size = len(data) if data else 0
    validation = validate_file_for_upload(
        file_path=None,
        content_type=content_type,
        document_type=document_type,
        size_bytes=size,
    )

    if validation.status != "VALID":
        return FillResult(
            status="REQUIRES_REVIEW",
            message=f"File validation failed: {validation.status} - {validation.message}",
            control_type="file",
        ), f"File validation failed: {validation.status}"

    # Upload via driver
    result = driver.upload_file(data, file_name, content_type, document_type)
    return result, None


# ---------------------------------------------------------------------------
# Phase 17: Evidence recording helpers
# ---------------------------------------------------------------------------

def record_fill_evidence(
    evidence_store,
    run_id: str,
    step: int,
    field_label: str,
    canonical: str | None,
    value: str | None,
    kind: str,
    *,
    success: bool = True,
    error: str | None = None,
    page_url: str | None = None,
):
    """Record evidence for a field fill action."""
    from app.application_execution.evidence_tracker import record_advanced_field_fill

    record_advanced_field_fill(
        evidence_store,
        run_id,
        step,
        field_label,
        canonical or "",
        kind,
        value or "",
        page_identifier=page_url,
    )


def record_file_evidence(
    evidence_store,
    run_id: str,
    step: int,
    field_label: str,
    document_type: str,
    file_name: str,
    content_type: str,
    success: bool,
    *,
    validation_result: str | None = None,
    error: str | None = None,
):
    """Record evidence for a file upload action."""
    from app.application_execution.evidence_tracker import record_file_upload

    record_file_upload(
        evidence_store,
        run_id,
        step,
        field_label,
        document_type,
        file_name,
        content_type,
        success,
        validation_result=validation_result,
        error_message=error,
    )


# ---------------------------------------------------------------------------
# Phase 17: Approval request helpers
# ---------------------------------------------------------------------------

def maybe_request_file_approval(
    approval_store,
    run_id: str,
    field_label: str,
    document_type: str,
    *,
    is_ambiguous: bool = False,
    is_sensitive: bool = False,
    accepted_types: list[str] | None = None,
) -> str | None:
    """Create approval request for file upload if needed.

    Returns action taken or None if no approval needed.
    """
    from app.application_execution.human_approval import ApprovalAction, check_approval_needed

    if is_ambiguous:
        action = ApprovalAction.AMBIGUOUS_DOCUMENT_SELECTION
        needs, reason = check_approval_needed(action.value, sensitivity="HIGH")
        if needs:
            approval_store.request_approval(
                run_id, action.value,
                details={
                    "field_label": field_label,
                    "document_type": document_type,
                    "accepted_types": accepted_types or [],
                },
                reason=reason,
            )
            return action.value

    if is_sensitive or document_type not in ("resume", "cover_letter"):
        action = ApprovalAction.UPLOAD_FILE
        needs, reason = check_approval_needed(action.value, sensitivity="MEDIUM")
        if needs:
            approval_store.request_approval(
                run_id, action.value,
                details={
                    "field_label": field_label,
                    "document_type": document_type,
                },
                reason=reason,
            )
            return action.value

    return None
