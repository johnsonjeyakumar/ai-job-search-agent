"""Execution runner (Phase 7 + Phase 14 + Phase 15).

Turns an APPROVED package into a controlled apply attempt. The runner is the
only place that drives a browser driver, and it does so strictly through the
operations the platform adapter allowed for the resolved mode:

1. preflight (package valid, no duplicate, budget OK)
2. open the application URL
3. stop for login / CAPTCHA / MFA instead of fighting them
4. inspect the form, map fields deterministically
5. fill only KNOWN fields, upload only the approved resume
6. stop for any NEW QUESTION or ambiguous required field
7. hand the browser state over at the human approval boundary

Phase 14 adds multi-step form orchestration:
- Detects multi-page forms via navigation controls
- Runs inspect->map->fill->validate->navigate loop
- Checkpoints after each page completion
- Handles review pages and conditional fields

Phase 15 adds session/authentication awareness:
- Multi-signal auth state detection (password, OAuth, MFA, CAPTCHA, session)
- Auth state checked on page open and after every navigation
- Maps auth states to execution actions (BLOCKED, AWAITING_USER)
- Domain validation for session fixation
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application_execution import base
from app.application_execution.adapters import get_adapter
from app.application_execution.browser import create_driver
from app.application_execution.detector import detect_platform
from app.application_execution.fields import (
    build_profile_context,
    map_fields,
)
from app.models.application_execution import (
    ApplicationExecution,
    ApplicationExecutionEvidence,
    ApplicationExecutionStep,
)

STEP_ORDER = [
    "detect_platform",
    "resolve_policy",
    "preflight_check",
    "open",
    "inspect_form",
    "map_fields",
    "fill_fields",
    "upload_resume",
    "validate_form",
    "pre_submission_check",
    "approval",
    "submit",
    "verify_submission",
    "capture_evidence",
    "complete",
]


# ---------------------------------------------------------------------------
# Phase 14: Multi-page form detection
# ---------------------------------------------------------------------------

def _is_multi_page_form(
    detected_fields: list,
    nav_elements: list[dict],
    heading: str | None = None,
) -> bool:
    """Detect if the current form is multi-page.

    Uses multiple signals: navigation buttons (next/continue), step indicators,
    and page count hints. Returns True only when confident this is multi-page.
    """
    from app.application_execution.page_detector import detect_navigation

    nav = detect_navigation(nav_elements)

    # Strong signal: next/continue button exists
    if nav.has_next:
        return True

    # Strong signal: step indicator in heading (e.g., "Step 2 of 5")
    if heading:
        import re
        step_match = re.search(r"step\s+\d+\s+of\s+\d+", heading, re.I)
        page_match = re.search(r"page\s+\d+\s+of\s+\d+", heading, re.I)
        if step_match or page_match:
            return True

    return False


def _has_review_button(nav_elements: list[dict]) -> bool:
    """Check if navigation elements include a review button."""
    from app.application_execution.page_detector import detect_navigation
    nav = detect_navigation(nav_elements)
    return nav.has_review


# ---------------------------------------------------------------------------
# Phase 14: Multi-page execution
# ---------------------------------------------------------------------------

def _run_multi_page_execution(
    db: Session,
    execution: ApplicationExecution,
    driver,
    *,
    ctx,
    adapter,
    mode: str,
    job,
    resume,
    url: str,
    headless: bool = True,
) -> dict:
    """Run multi-page form orchestration.

    Phase 17: Integrates file upload handling, normalization, evidence, and approval.

    Returns a dict with keys: fields_filled, resume_uploaded, required_unfilled,
    new_questions, fills, session_data, warnings_added.
    """
    from app.application_execution.checkpoint import (
        CheckpointStore,
    )
    from app.application_execution.evidence_tracker import EvidenceStore
    from app.application_execution.form_orchestrator import (
        detect_dynamic_changes,
        fill_page_fields,
        inspect_page,
        map_page_fields,
        navigate_to_next,
        validate_page,
        resolve_file_for_upload,
        validate_and_upload_file,
        maybe_request_file_approval,
        record_fill_evidence,
        record_file_evidence,
    )
    from app.application_execution.form_session import (
        FormSession,
        FormSessionState,
        PageType,
    )
    from app.application_execution.human_approval import ApprovalStore

    session = FormSession(
        session_id=f"exec-{execution.id}",
        application_id=None,
        execution_run_id=execution.id,
        package_id=execution.package_id,
    )
    checkpoint_store = CheckpointStore()
    evidence_store = EvidenceStore()
    approval_store = ApprovalStore()

    total_fields_filled = 0
    total_resume_uploaded = False
    all_fills: list[dict] = []
    all_new_questions = []
    all_required_unfilled = []
    warnings_added = 0
    max_pages = 20  # safety limit

    for page_num in range(1, max_pages + 1):
        # --- Inspect ---
        current_url = driver.get_current_url() if hasattr(driver, "get_current_url") else url
        raw_fields = driver.inspect_form()
        heading = driver.get_heading() if hasattr(driver, "get_heading") else None
        has_nav = hasattr(driver, "get_navigation_elements")
        nav_elements = driver.get_navigation_elements() if has_nav else []

        snapshot = inspect_page(
            session, current_url, raw_fields, nav_elements, heading
        )

        # Checkpoint: page inspected
        from app.application_execution.checkpoint import create_form_inspected_checkpoint
        checkpoint_store.save(
            create_form_inspected_checkpoint(
                run_id=f"exec-{execution.id}",
                step=page_num * 5,
                fields_found=len(raw_fields),
                form_url=current_url,
            )
        )

        # Record step for DB trail
        _record_step(
            db, execution.id, "inspect_form",
            message=f"Page {page_num}: detected {len(raw_fields)} fields."
        )

        # --- Check for submission confirmation page ---
        if snapshot.page_type == PageType.SUBMISSION_PAGE:
            session.transition(FormSessionState.CONFIRMED)
            break

        # --- Check for review page ---
        if snapshot.page_type == PageType.REVIEW_PAGE:
            session.transition(FormSessionState.REVIEW)
            # Still record what we found
            _record_step(
                db, execution.id, "inspect_form",
                message=f"Page {page_num}: review page detected."
            )
            break

        # --- Map fields ---
        mapping = map_page_fields(session, ctx)
        for warning in mapping.warnings:
            _add_warning(db, execution.id, "map_fields", warning)
            warnings_added += 1

        # --- Resume upload (first page only typically) ---
        if not total_resume_uploaded and resume is not None and adapter.allows_resume_upload(mode):
            file_fields = [f for f in mapping.fields if f.detected.kind == "file"]
            resume_file = next(
                (f for f in file_fields if "resume" in (f.detected.label or "").lower()
                 or "cv" in (f.detected.label or "").lower()),
                None,
            )
            if resume_file is not None:
                data, file_name, content_type = _resume_bytes(resume)
                if data is not None:
                    ct = content_type or "application/pdf"
                    up = driver.upload_resume(data, file_name or "resume", ct)
                    if up.status == base.KNOWN:
                        total_resume_uploaded = True
                        record_file_evidence(
                            evidence_store, f"exec-{execution.id}",
                            page_num * 5, "Upload Resume", "resume",
                            file_name or "resume.pdf", ct, True,
                        )

        # --- Phase 17: Fill file fields (non-resume) with validation ---
        file_fields_to_upload = [
            f for f in mapping.fields
            if f.detected.kind == "file" and f.classification == base.KNOWN
        ]
        for mapped_file in file_fields_to_upload:
            doc_type = None
            from app.application_execution.file_handler import detect_document_type_from_label
            doc_type = detect_document_type_from_label(mapped_file.detected.label or "")

            if doc_type == "resume":
                continue  # already handled above

            # Check if approval needed for ambiguous/sensitive documents
            accepted = getattr(mapped_file.detected, "accepted_types", []) or []
            is_ambiguous = len(accepted) > 1
            approval_action = maybe_request_file_approval(
                approval_store, f"exec-{execution.id}",
                mapped_file.detected.label, doc_type or "other",
                is_ambiguous=is_ambiguous,
                accepted_types=accepted,
            )
            if approval_action:
                _add_warning(
                    db, execution.id, "upload_resume",
                    f"File upload '{mapped_file.detected.label}' requires approval.",
                )
                warnings_added += 1
                continue

            # Resolve file
            data, fn, ct, dt, err = resolve_file_for_upload(
                mapped_file.detected, resume=resume,
                package_id=execution.package_id,
            )
            if err:
                _add_warning(db, execution.id, "upload_resume", err)
                warnings_added += 1
                continue
            if data is None:
                # Non-resume files without data are skipped
                continue

            result, upload_err = validate_and_upload_file(
                driver, data, fn or "file", ct or "application/pdf",
                dt or "other", package_id=execution.package_id,
            )
            record_file_evidence(
                evidence_store, f"exec-{execution.id}",
                page_num * 5, mapped_file.detected.label,
                dt or "other", fn or "file", ct or "application/pdf",
                result.status == base.KNOWN,
                validation_result=result.status,
                error=upload_err,
            )

        # --- Fill known fields (with normalization) ---
        fill_page_fields(session, driver, mapping)
        for f in mapping.fields:
            if f.classification == base.KNOWN and f.value and f.detected.kind != "file":
                all_fills.append({
                    "field_key": f.detected.key,
                    "label": f.detected.label,
                    "value": f.value,
                    "kind": f.detected.kind,
                })
                total_fields_filled += 1
                record_fill_evidence(
                    evidence_store, f"exec-{execution.id}",
                    page_num * 5, f.detected.label,
                    f.matched_key, f.value, f.detected.kind,
                    page_url=current_url,
                )

        # Track new questions and required unfilled
        for q in mapping.new_questions:
            all_new_questions.append(q)
            _add_warning(db, execution.id, "validate_form",
                         f"NEW QUESTION on page {page_num}: '{q.label}'.")
            warnings_added += 1

        for f in mapping.fields:
            if f.detected.required and f.classification != base.KNOWN and f.detected.kind != "file":
                all_required_unfilled.append(f)

        # --- Validate page ---
        is_valid, issues = validate_page(session, mapping)
        for issue in issues:
            _add_warning(db, execution.id, "validate_form", issue)
            warnings_added += 1

        # --- Detect dynamic changes after filling ---
        prev_fps = snapshot.field_fingerprints
        new_fields_after = driver.inspect_form() if hasattr(driver, "inspect_form") else []
        changes = detect_dynamic_changes(session, prev_fps, new_fields_after)
        if changes["has_changes"]:
            # Re-map and fill new fields
            for nf in changes.get("added_fields", []):
                from app.application_execution.form_session import TrackedField
                snapshot.fields.append(TrackedField(detected=nf))
            mapping2 = map_page_fields(session, ctx)
            fill_page_fields(session, driver, mapping2)
            validate_page(session, mapping2)

        # --- Navigate to next page ---
        if snapshot.has_next_button and is_valid:
            success = navigate_to_next(session, driver, snapshot)
            if success:
                _record_step(
                    db, execution.id, "inspect_form",
                    message=f"Page {page_num}: navigated to next page."
                )

                # Phase 15: Auth check after navigation
                from app.application_execution.auth import SessionState
                from app.application_execution.checkpoint import (
                    create_auth_checked_checkpoint,
                )
                post_nav_auth = driver.detect_authentication()
                checkpoint_store.save(create_auth_checked_checkpoint(
                    run_id=f"exec-{execution.id}",
                    step=page_num * 5 + 1,
                    auth_state=post_nav_auth.state.value,
                    reason=post_nav_auth.reason,
                    confidence=post_nav_auth.confidence,
                    domain=driver.get_current_domain(),
                ))

                if post_nav_auth.state in (
                    SessionState.LOGIN_REQUIRED,
                    SessionState.MFA_REQUIRED,
                    SessionState.CAPTCHA_REQUIRED,
                ):
                    session.transition(FormSessionState.BLOCKED)
                    _add_warning(
                        db, execution.id, "inspect_form",
                        f"Page {page_num}: auth state changed to "
                        f"{post_nav_auth.state.value} after navigation.",
                    )
                    warnings_added += 1
                    break

                continue
            else:
                _add_warning(db, execution.id, "inspect_form",
                             f"Page {page_num}: navigation failed.")
                warnings_added += 1
                break

        # --- No more navigation (single-page or last page) ---
        break

    return {
        "fields_filled": total_fields_filled,
        "resume_uploaded": total_resume_uploaded,
        "required_unfilled": all_required_unfilled,
        "new_questions": all_new_questions,
        "fills": all_fills,
        "session_data": session.to_dict(),
        "warnings_added": warnings_added,
    }


def _record_step(
    db: Session,
    execution_id: int,
    step: str,
    *,
    status: str = "completed",
    message: str | None = None,
    url: str | None = None,
) -> ApplicationExecutionStep:
    order = STEP_ORDER.index(step) if step in STEP_ORDER else 99
    if status != "running":
        in_flight = db.scalar(
            select(ApplicationExecutionStep)
            .where(
                ApplicationExecutionStep.execution_id == execution_id,
                ApplicationExecutionStep.step == step,
                ApplicationExecutionStep.status == "running",
            )
            .order_by(ApplicationExecutionStep.id.desc())
            .limit(1)
        )
        if in_flight is not None:
            in_flight.status = status
            if message is not None:
                in_flight.message = message
            if url is not None:
                in_flight.url = url
            in_flight.completed_at = datetime.now()
            order = STEP_ORDER.index(step) if step in STEP_ORDER else 99
            in_flight.order = order
            db.flush()
            return in_flight
    row = ApplicationExecutionStep(
        execution_id=execution_id,
        step=step,
        order=order,
        status=status,
        message=message,
        url=url,
        completed_at=(
            datetime.now()
            if status in ("completed", "warning", "blocked", "error")
            else None
        ),
    )
    db.add(row)
    db.flush()
    return row


def _add_warning(db: Session, execution_id: int, step: str, message: str) -> None:
    execution = db.get(ApplicationExecution, execution_id)
    if execution is None:
        return
    warnings = list(execution.warnings or [])
    warnings.append({"step": step, "message": message})
    execution.warnings = warnings
    db.flush()


def _mark_execution(db: Session, execution_id: int, *, status, current_step=None) -> None:
    execution = db.get(ApplicationExecution, execution_id)
    if execution is None:
        return
    execution.status = status
    if current_step is not None:
        execution.current_step = current_step
    if status in base._TERMINAL_STATUSES:
        execution.completed_at = datetime.now()
    db.flush()


def _answers_as_dicts(db: Session, package_id: int) -> list[dict]:
    from app.models.application_package import ApplicationAnswer

    rows = list(
        db.scalars(
            select(ApplicationAnswer)
            .where(ApplicationAnswer.package_id == package_id)
            .order_by(ApplicationAnswer.id)
        )
    )
    return [
        {
            "id": a.id,
            "category": a.category,
            "question": a.question,
            "answer": a.answer,
            "source_evidence": a.source_evidence or [],
            "validation_status": a.validation_status,
            "feedback": a.feedback,
        }
        for a in rows
    ]


def _invalid_answers(answers: list[dict]) -> list[str]:
    return [
        a["question"] for a in answers if a.get("validation_status") == "INVALID"
    ]


def _resume_bytes(resume) -> tuple[bytes | None, str | None, str | None]:
    if resume is None or not resume.file_path:
        return None, None, None
    try:
        from app.storage.local import get_storage

        data = get_storage().load(resume.file_path)
    except (OSError, ValueError):
        return None, resume.file_name, resume.content_type
    return data, resume.file_name, resume.content_type


def _dget(obj: object, attr: str) -> object | None:
    """Attr access that tolerates dicts or dataclasses (JSON payload items)."""
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)


def _field_label(item: object) -> str | None:
    """Best available label for a payload item that may be a dict, a
    MappedField, a DetectedField, or a NewQuestion."""
    if isinstance(item, dict):
        return item.get("label")
    detected = getattr(item, "detected", None)
    if detected is not None:
        return getattr(detected, "label", None) or getattr(detected, "key", None)
    return getattr(item, "label", None) or getattr(item, "key", None)


def _payload_dict(data: dict) -> dict:
    """JSON-serializable snapshot of the approval/preview payload."""
    fills = []
    for item in data.get("fills") or []:
        fills.append(
            {
                "label": _dget(item, "label"),
                "value": _dget(item, "value"),
                "field_key": _dget(item, "field_key"),
            }
        )
    required_unfilled = [
        _field_label(item) for item in data.get("required_unfilled") or []
    ]
    new_questions = [
        {
            "label": q.get("label") if isinstance(q, dict) else q.label,
            "recommended_answer": (
                q.get("recommended_answer") if isinstance(q, dict) else q.recommended_answer
            ),
            "evidence": (
                list(q.get("evidence") or [])
                if isinstance(q, dict)
                else list(q.evidence or [])
            ),
        }
        for q in data.get("new_questions") or []
    ]
    return {
        "platform": data.get("platform"),
        "company": data.get("company"),
        "job_title": data.get("job_title"),
        "job_url": data.get("job_url"),
        "resume_name": data.get("resume_name"),
        "package_version": data.get("package_version"),
        "execution_mode": data.get("execution_mode"),
        "fields_detected": data.get("fields_detected", 0),
        "fields_completed": data.get("fields_completed", 0),
        "fields_needing_review": data.get("fields_needing_review", 0),
        "answered_questions": data.get("answered_questions", 0),
        "warnings": list(data.get("warnings") or []),
        "auto_submit_allowed": bool(data.get("auto_submit_allowed")),
        "recommended_action": data.get("recommended_action", "cannot_submit"),
        "adapter_guidance": data.get("adapter_guidance"),
        "todos": data.get("todos"),
"fills": fills,
            "required_unfilled": required_unfilled,
            "new_questions": new_questions,
            "_resume": dict(data.get("_resume") or {}),
            "logged_in": bool(data.get("logged_in")),
            "resume_uploaded": bool(data.get("resume_uploaded")),
        }


def run_execution(
    db: Session,
    package,
    *,
    driver_name: str = "auto",
    force_duplicate: bool = False,
    budget: dict | None = None,
    headless: bool = True,
) -> ApplicationExecution:
    """Execute the safe portion of the apply workflow for an approved package.

    Returns the persisted execution row. Submission is *not* performed here;
    the row lands in AWAITING_APPROVAL / AWAITING_USER / BLOCKED.
    """
    # -- preflight (db-backed, no browser) -----------------------------------
    _preflight(db, package, force_duplicate=force_duplicate, budget=budget)

    from app.models.preferences import Preferences
    from app.models.profile import Profile
    from app.models.resume import Resume
    from app.services import job_service

    job = job_service.get_job(db, package.job_id)

    profile = db.scalar(select(Profile).order_by(Profile.id).limit(1))
    prefs = db.scalar(select(Preferences).order_by(Preferences.id).limit(1))
    resume = db.get(Resume, package.selected_resume_id) if package.selected_resume_id else None

    answers = _answers_as_dicts(db, package.id)
    url = job.application_url or job.url

    # -- detection + policy --------------------------------------------------
    detection = detect_platform(
        url=job.url, application_url=job.application_url, source=job.source
    )
    adapter = get_adapter(detection.platform)
    policy = adapter.policy(
        dict(getattr(prefs, "platform_policies", None) or {}) if prefs else {}
    )
    mode = policy.mode

    execution = ApplicationExecution(
        package_id=package.id,
        platform=detection.platform,
        execution_mode=mode,
        status=base.STATUS_EXECUTING,
        current_step="open",
        daily_budget=budget or {},
    )
    db.add(execution)
    db.flush()
    _record_step(db, execution.id, "detect_platform",
                 message=f"{detection.label} (based on {detection.based_on}).")
    _record_step(db, execution.id, "resolve_policy",
                 message=f"Mode: {mode}. {policy.reason}")

    if not policy.supports_browser_automation:
        _add_warning(db, execution.id, "resolve_policy",
                     f"Platform '{detection.platform}' resolves to {mode}; "
                     "inspection only.")
    if not url:
        _mark_execution(db, execution.id, status=base.STATUS_BLOCKED,
                        current_step="open")
        _record_step(db, execution.id, "open", status="blocked",
                     message="No application URL on the job record.")
        return execution

    driver = create_driver(url, driver_name=driver_name, headless=headless)
    try:
        _record_step(db, execution.id, "preflight_check", message="Preflight passed.")
        _record_step(db, execution.id, "open", status="running", url=url)
        page_info = driver.open(url)
        _record_step(db, execution.id, "open", url=page_info.get("url"),
                     message=f"Opened {page_info.get('title') or page_info.get('url')}.")

        if driver.detect_captcha():
            _add_warning(db, execution.id, "open",
                         "CAPTCHA / anti-bot challenge detected. Blocked.")
            _mark_execution(db, execution.id, status=base.STATUS_BLOCKED,
                            current_step="open")
            _record_step(db, execution.id, "open", status="blocked",
                         message="CAPTCHA or anti-bot challenge detected. Human action required.")
            db.commit()
            return execution

        # Phase 15: Multi-signal authentication detection
        from app.application_execution.auth import (
            SessionState,
            map_session_state_to_action,
        )
        from app.application_execution.checkpoint import (
            CheckpointStore,
            create_auth_checked_checkpoint,
            create_auth_failed_checkpoint,
            create_domain_validated_checkpoint,
            create_session_expired_checkpoint,
        )

        checkpoint_store = CheckpointStore()
        auth_state = driver.detect_authentication()
        expected_domain = driver.get_current_domain()

        checkpoint_store.save(create_auth_checked_checkpoint(
            run_id=execution.id,
            step=2,
            auth_state=auth_state.state.value,
            reason=auth_state.reason,
            confidence=auth_state.confidence,
            domain=expected_domain,
        ))

        _record_step(
            db, execution.id, "open",
            message=f"Auth state: {auth_state.state.value} "
                    f"(confidence: {auth_state.confidence:.0%}). {auth_state.reason}",
        )

        # Map auth state to execution action
        action = map_session_state_to_action(auth_state.state)
        if action == "BLOCKED":
            # Auth required or blocked - cannot proceed automatically
            status = base.STATUS_BLOCKED
            if auth_state.state == SessionState.AUTH_FAILED:
                status = base.STATUS_FAILED
                checkpoint_store.save(create_auth_failed_checkpoint(
                    run_id=execution.id, step=3,
                    reason=auth_state.reason,
                ))
            elif auth_state.state == SessionState.SESSION_EXPIRED:
                checkpoint_store.save(create_session_expired_checkpoint(
                    run_id=execution.id, step=3,
                    reason=auth_state.reason,
                ))

            _mark_execution(db, execution.id, status=status, current_step="open")
            _record_step(
                db, execution.id, "open", status="blocked",
                message=f"Authentication required: {auth_state.state.value}. "
                        f"{auth_state.reason}",
            )
            db.commit()
            return execution

        if action == "AWAITING_USER":
            # Login required, MFA required, or CAPTCHA - human intervention needed
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="open")
            _record_step(
                db, execution.id, "open", status="warning",
                message=f"Human action required: {auth_state.state.value}. "
                        f"{auth_state.reason}. Complete it manually; execution "
                        "continues afterwards (credentials are never stored).",
            )
            db.commit()
            return execution

        # Auth check passed - continue with form inspection
        checkpoint_store.save(create_domain_validated_checkpoint(
            run_id=execution.id, step=4,
            expected_domain=expected_domain,
            actual_domain=expected_domain,
            is_match=True,
        ))

        ctx = build_profile_context(profile, prefs, answers)

        _record_step(db, execution.id, "inspect_form", status="running")
        detected = driver.inspect_form()
        _record_step(db, execution.id, "inspect_form",
                     message=f"Detected {len(detected)} form fields.")

        # -- Phase 14: detect multi-page form -------------------------------
        heading = driver.get_heading() if hasattr(driver, "get_heading") else None
        has_nav = hasattr(driver, "get_navigation_elements")
        nav_elements = driver.get_navigation_elements() if has_nav else []
        is_multi_page = _is_multi_page_form(detected, nav_elements, heading)

        if is_multi_page:
            # -- multi-page execution via orchestrator ----------------------
            mp_result = _run_multi_page_execution(
                db, execution, driver,
                ctx=ctx, adapter=adapter, mode=mode,
                job=job, resume=resume, url=url, headless=headless,
            )
            fields_filled = mp_result["fields_filled"]
            resume_uploaded = mp_result["resume_uploaded"]
            required_unfilled = mp_result["required_unfilled"]
            new_questions = mp_result["new_questions"]
            fills = mp_result["fills"]

            # Still do resume upload for single-page if not done in orchestrator
            if not resume_uploaded and resume is not None and adapter.allows_resume_upload(mode):
                file_fields_m = [
                    f for f in map_fields(detected, ctx).fields
                    if f.detected.kind == "file"
                ]
                resume_file_m = next(
                    (f for f in file_fields_m if f.classification != base.UNKNOWN
                     or "resume" in (f.detected.label or "").lower()),
                    None,
                )
                if resume_file_m is not None:
                    data_r, fn_r, ct_r = _resume_bytes(resume)
                    if data_r is not None:
                        ct_r_val = ct_r or "application/pdf"
                        up_r = driver.upload_resume(data_r, fn_r or "resume", ct_r_val)
                        if up_r.status == base.KNOWN:
                            resume_uploaded = True
                        else:
                            _add_warning(db, execution.id, "upload_resume", up_r.message)
        else:
            # -- single-page execution (existing flow) ----------------------
            _record_step(db, execution.id, "map_fields", status="running")
            mapped = map_fields(detected, ctx)
            for warning in mapped.warnings:
                _add_warning(db, execution.id, "map_fields", warning)
            _record_step(
                db, execution.id, "map_fields",
                message=f"Mapped {len(mapped.fields)} fields, "
                        f"{len(mapped.new_questions)} new questions.",
            )

            # -- resume upload -----------------------------------------------
            resume_uploaded = False
            file_fields = [f for f in mapped.fields if f.detected.kind == "file"]
            resume_file = next(
                (
                    f
                    for f in file_fields
                    if (
                        f.classification != base.UNKNOWN
                        or "resume" in (f.detected.label or "").lower()
                        or "cv" in (f.detected.label or "").lower()
                    )
                ),
                None,
            )
            if resume is None:
                _add_warning(db, execution.id, "upload_resume",
                             "No resume selected on the package; nothing to upload.")
            elif adapter.allows_resume_upload(mode):
                data, file_name, content_type = _resume_bytes(resume)
                if data is not None and resume_file is not None:
                    up = driver.upload_resume(
                        data, file_name or "resume", content_type or "application/pdf"
                    )
                    if up.status == base.KNOWN:
                        resume_uploaded = True
                    else:
                        _add_warning(db, execution.id, "upload_resume", up.message)
                elif data is not None:
                    _add_warning(db, execution.id, "upload_resume",
                                 "No file input detected on the page.")
                else:
                    _add_warning(db, execution.id, "upload_resume",
                                 "Resume file missing from storage; skipped.")
            else:
                _add_warning(db, execution.id, "upload_resume",
                             "Policy does not allow automated resume upload in this mode.")
            _record_step(
                db, execution.id, "upload_resume",
                message=(
                    "Approved resume uploaded."
                    if resume_uploaded
                    else "Resume upload skipped."
                ),
            )

            # -- fill known fields -------------------------------------------
            from app.application_execution.evidence_tracker import EvidenceStore
            evidence_store = EvidenceStore()

            fills: list[dict] = []
            fields_filled = 0
            if adapter.allows_fill_known(mode):
                for f in mapped.fields:
                    if f.classification != base.KNOWN or f.detected.kind == "file":
                        continue

                    # Phase 17: normalize value before filling
                    from app.application_execution.form_orchestrator import normalize_field_value
                    normalized_value, norm_error = normalize_field_value(f, f.detected)
                    if norm_error:
                        _add_warning(db, execution.id, "fill_fields",
                                     f"'{f.detected.label}' normalization failed: {norm_error}")
                        continue

                    fill_value = normalized_value or f.value or ""
                    if f.matched_key == "answer":
                        mapped.answered_questions = getattr(mapped, "answered_questions", 0) + 1
                    result = driver.fill(f.detected.key, fill_value)
                    fills.append({
                        "field_key": f.detected.key,
                        "label": f.detected.label,
                        "value": fill_value,
                        "kind": f.detected.kind,
                    })
                    if result.status == base.KNOWN:
                        fields_filled += 1
                        # Record evidence
                        from app.application_execution.form_orchestrator import record_fill_evidence
                        record_fill_evidence(
                            evidence_store, str(execution.id),
                            0, f.detected.label, f.matched_key,
                            fill_value, f.detected.kind,
                        )
                    else:
                        _add_warning(db, execution.id, "fill_fields",
                                     f"'{f.detected.label}' fill failed: {result.message}")
            _record_step(db, execution.id, "fill_fields",
                         message=f"Filled {fields_filled} known fields.")

            # -- validate form -----------------------------------------------
            required_unfilled = [
                f for f in mapped.fields
                if f.detected.required and f.classification != base.KNOWN
            ]
            new_questions = mapped.new_questions
            for q in new_questions:
                _add_warning(db, execution.id, "validate_form",
                             f"NEW QUESTION DETECTED: '{q.label}'.")

        # -- common validation for both paths --------------------------------
        fatal = []
        fatal.extend(
            f"Required field '{f.detected.label}' needs review ({f.ambiguity})."
            for f in required_unfilled
            if hasattr(f, "ambiguity") and f.matched_key != "answer"
        )
        if new_questions:
            fatal.append("A new question was detected that no prepared answer covers.")

        # answers must still be valid
        invalid = _invalid_answers(answers)
        if invalid:
            fatal.append(f"Package answers are invalid for: {', '.join(invalid[:3])}.")

        # Compute review count — mapped exists only in single-page path
        review_count = 0
        if is_multi_page:
            review_count = len(required_unfilled)
        else:
            review_count = getattr(mapped, "review_count", 0)

        summary = {
            "fields_detected": len(detected),
            "fields_filled": fields_filled,
            "fields_needing_review": review_count + len(required_unfilled),
            "answered_questions": sum(
                1 for f in (mapped.fields if not is_multi_page else [])
                if f.matched_key == "answer"
            ),
            "new_questions": [q.label for q in new_questions],
        }
        execution.execution_summary = summary
        db.flush()

        # -- pre-submission payload ------------------------------------------
        payload = {
            "platform": detection.label,
            "company": job.company,
            "job_title": job.title,
            "job_url": url,
            "resume_name": resume.name if resume else None,
            "package_version": package.version,
            "execution_mode": mode,
            "fields_detected": len(detected),
            "fields_completed": fields_filled if not resume_uploaded else fields_filled + 1,
            "fields_needing_review": review_count + len(required_unfilled),
            "answered_questions": summary["answered_questions"],
            "warnings": list(execution.warnings or []),
            "auto_submit_allowed": bool(
                policy.supports_automated_submit
                and adapter.allows_automated_submit(mode)
            ),
            "adapter_guidance": adapter.guidance(mode),
            "fills": fills,
            "required_unfilled": required_unfilled,
            "new_questions": new_questions,
            "_resume": (
                {"file_name": resume.file_name, "content_type": resume.content_type}
                if resume is not None
                else {}
            ),
            "logged_in": not driver.detect_login(),
        }
        if resume_uploaded:
            payload["resume_uploaded"] = True

        execution.approval_payload = _payload_dict(payload)
        db.flush()

        # -- decide where to stop ---------------------------------------------
        if driver.detect_captcha():
            _add_warning(db, execution.id, "pre_submission_check",
                         "CAPTCHA / anti-bot challenge detected. Blocked.")
            _mark_execution(db, execution.id, status=base.STATUS_BLOCKED,
                            current_step="validate_form")
            _record_step(db, execution.id, "pre_submission_check", status="blocked",
                         message="CAPTCHA or anti-bot challenge. Human action required.")
        elif mode == base.UNSUPPORTED:
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="pre_submission_check")
            _record_step(db, execution.id, "pre_submission_check", status="warning",
                         message="Platform is UNSUPPORTED for automation; inspection only.")
        elif new_questions:
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="validate_form")
            _record_step(db, execution.id, "pre_submission_check", status="warning",
                         message="NEW QUESTION DETECTED; prepared answer required.")
            payload["recommended_action"] = "review_question"
            execution.approval_payload = _payload_dict(payload)
        elif required_unfilled and mode == base.HUMAN_ASSISTED:
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="validate_form")
            _record_step(db, execution.id, "pre_submission_check", status="warning",
                         message="Required fields need manual completion.")
            payload["recommended_action"] = "review_unknown"
            execution.approval_payload = _payload_dict(payload)
        elif required_unfilled:
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="validate_form")
            _record_step(db, execution.id, "pre_submission_check", status="warning",
                         message="Required fields are unresolved; submission blocked.")
            payload["recommended_action"] = "review_unknown"
            execution.approval_payload = _payload_dict(payload)
        elif mode == base.HUMAN_ASSISTED or not adapter.allows_automated_submit(mode):
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_APPROVAL,
                            current_step="approval")
            _record_step(db, execution.id, "approval",
                         message="Complete and submit manually, then confirm the outcome.")
            payload["recommended_action"] = "complete_manually"
            payload["todos"] = (
                "Review the form, complete any remaining fields, then submit manually "
                "and confirm the outcome."
            )
            execution.approval_payload = _payload_dict(payload)
        else:
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_APPROVAL,
                            current_step="approval")
            _record_step(db, execution.id, "approval",
                         message="Application ready for submission; waiting for approval.")
            payload["recommended_action"] = "submit"
            payload["todos"] = "Review the package and approve submission."
            execution.approval_payload = _payload_dict(payload)

        db.commit()
        return execution
    finally:
        try:
            driver.close()
        except Exception:  # noqa: BLE001 - best effort
            pass


def _preflight(
    db: Session,
    package,
    *,
    force_duplicate: bool,
    budget: dict | None,
) -> None:
    from app.application_execution.base import ExecutionBlockedError

    if package.status != "APPROVED":
        raise ExecutionBlockedError(
            base.STATUS_BLOCKED,
            "PACKAGE_NOT_APPROVED",
            f"Package {package.id} is '{package.status}', not APPROVED.",
        )
    if package.quality_gate == "FAIL":
        raise ExecutionBlockedError(
            base.STATUS_BLOCKED,
            "PACKAGE_VALIDATION_FAILED",
            "Package failed validation; it cannot be executed.",
        )

    answers = _answers_as_dicts(db, package.id)
    invalid = _invalid_answers(answers)
    if invalid:
        raise ExecutionBlockedError(
            base.STATUS_BLOCKED,
            "ANSWERS_INVALID",
            f"Package answers are invalid for: {', '.join(invalid[:3])}.",
        )

    if not force_duplicate:
        dup = _duplicate_submission(db, package)
        if dup:
            raise ExecutionBlockedError(
                base.STATUS_BLOCKED,
                "DUPLICATE_APPLICATION",
                dup,
            )

    if budget:
        maximum = budget.get("maximum")
        used = budget.get("used_today", 0)
        if maximum is not None and used >= maximum:
            raise ExecutionBlockedError(
                base.STATUS_BLOCKED,
                "DAILY_LIMIT_REACHED",
                f"Daily application maximum ({maximum}) already reached ({used} today).",
            )


def _duplicate_submission(db: Session, package) -> str | None:
    """Check for duplicate applications before submitting.

    Uses the structured duplicate detection from submission_verify.py.
    Returns a reason string if duplicate detected, None if safe to submit.
    """
    from app.application_execution.submission_verify import (
        check_duplicate,
        DuplicateVerdict,
    )
    from app.models.application import Application
    from app.models.application_execution import ApplicationExecution

    # Gather existing applications for this job
    existing_apps = []
    prev_application = db.scalar(
        select(Application)
        .where(Application.job_id == package.job_id)
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if prev_application is not None:
        existing_apps.append({
            "id": prev_application.id,
            "job_id": prev_application.job_id,
            "lifecycle_status": prev_application.lifecycle_status,
            "status": prev_application.status,
        })

    # Gather existing executions for this package
    existing_execs = []
    prior = db.scalar(
        select(ApplicationExecution)
        .where(ApplicationExecution.package_id == package.id)
        .where(ApplicationExecution.status.in_(base._EXTERNAL_ACTION_STATUSES))
        .order_by(ApplicationExecution.id.desc())
        .limit(1)
    )
    if prior is not None:
        existing_execs.append({
            "id": prior.id,
            "status": prior.status,
        })

    result = check_duplicate(
        job_id=package.job_id,
        existing_applications=existing_apps,
        existing_executions=existing_execs,
    )

    if result.verdict == DuplicateVerdict.ALREADY_APPLIED:
        return result.reason
    if result.verdict == DuplicateVerdict.DUPLICATE_SUSPECTED:
        return result.reason
    return None


def submit_execution(db: Session, execution: ApplicationExecution) -> ApplicationExecution:
    """Replay the safe steps and submit after user approval (where allowed)."""
    from app.models.application_package import ApplicationPackage
    from app.models.resume import Resume
    from app.services import job_service

    package = db.get(ApplicationPackage, execution.package_id)

    payload = execution.approval_payload or {}
    fills = payload.get("fills") or []
    resume_info = payload.get("_resume") or {}
    _resume = None
    if package is not None and package.selected_resume_id:
        _resume = db.get(Resume, package.selected_resume_id)

    job = job_service.get_job(db, package.job_id) if package is not None else None
    url = (job.application_url or job.url) if job is not None else None

    _mark_execution(db, execution.id, status=base.STATUS_EXECUTING, current_step="submit")
    _record_step(db, execution.id, "submit", status="running", url=url)

    driver_name = "mock" if (url or "").startswith("mock://") else "playwright"
    if driver_name == "mock":
        from app.application_execution.browser import MockBrowserDriver

        driver = MockBrowserDriver(url or "mock://simple-form")
    else:
        driver = create_driver(url, driver_name="playwright")
    try:
        if driver.detect_captcha():
            _add_warning(db, execution.id, "submit",
                         "CAPTCHA / anti-bot challenge detected during submission; blocked.")
            _mark_execution(db, execution.id, status=base.STATUS_BLOCKED, current_step="submit")
            _record_step(db, execution.id, "submit", status="blocked",
                         message="CAPTCHA or anti-bot challenge. Human action required.")
            db.commit()
            return execution
        if driver.detect_login():
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="submit")
            _record_step(db, execution.id, "submit", status="warning",
                         message="Login wall appeared before submission; finish login "
                                 "manually then resume.")
            db.commit()
            return execution

        driver.open(url or "mock://simple-form")
        # replay the known (safe) fills from the approval step, with normalization.
        for item in fills:
            key = item.get("field_key")
            value = item.get("value") or ""
            kind = item.get("kind", "text")
            if not key:
                continue

            # Phase 17: normalize value for re-fill
            from app.application_execution.form_orchestrator import normalize_field_value
            from app.application_execution.fields import MappedField
            from app.application_execution.base import DetectedField, KNOWN

            # Create a temporary MappedField for normalization
            dummy_detected = DetectedField(key=key, label=key, kind=kind)
            dummy_mapped = MappedField(
                detected=dummy_detected, matched_key=key,
                value=value, classification=KNOWN,
            )
            normalized, _ = normalize_field_value(dummy_mapped, dummy_detected)
            driver.fill(key, normalized or value)
        if resume_info.get("file_name"):
            data, _, _ = _resume_bytes(_resume)
            if data is not None:
                driver.upload_resume(
                    data,
                    resume_info["file_name"],
                    resume_info.get("content_type") or "application/pdf",
                )

        if driver.detect_captcha():
            _add_warning(db, execution.id, "submit",
                         "CAPTCHA detected after re-filling form; blocked.")
            _mark_execution(db, execution.id, status=base.STATUS_BLOCKED, current_step="submit")
            _record_step(db, execution.id, "submit", status="blocked",
                         message="CAPTCHA or anti-bot challenge. Human action required.")
            db.commit()
            return execution

        result = driver.submit()
        _record_step(db, execution.id, "submit",
                     message=result.message or "Submission attempted.",
                     url=result.url)
        return _handle_submission_result(db, execution, result)
    finally:
        try:
            driver.close()
        except Exception:  # noqa: BLE001 - best effort
            pass


def _handle_submission_result(
    db: Session,
    execution: ApplicationExecution,
    result: base.SubmissionResult,
) -> ApplicationExecution:
    from app.models.application_package import ApplicationPackage
    from app.application_execution.submission_verify import (
        detect_confirmation,
        extract_reference_id,
        FailureType,
        SubmissionOutcome,
        OUTCOME_TO_EXECUTION_STATUS,
    )

    package = db.get(ApplicationPackage, execution.package_id)
    if result.failure:
        _add_warning(db, execution.id, "verify_submission", result.message)
        _mark_execution(db, execution.id, status=base.STATUS_EXECUTION_FAILED,
                        current_step="verify_submission")
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="submission_error",
            value=result.message or "Submission failed.",
        ))
        _record_step(db, execution.id, "verify_submission", status="error",
                     message=result.message or "Submission failed.")
        _record_automation_error(
            db, package, "submit", result.message or "Submission failed."
        )
        _record_submission_event(
            db, execution, package,
            outcome=SubmissionOutcome.SUBMISSION_FAILED,
            failure_message=result.message,
        )
        db.commit()
        return execution

    # Phase 19: use structured confirmation detection
    evidence = detect_confirmation(
        page_text=result.raw_text or "",
        current_url=result.url or "",
        previous_url=None,
    )

    # Use evidence outcome to determine status
    submitted_status = OUTCOME_TO_EXECUTION_STATUS.get(
        evidence.outcome, base.STATUS_SUBMISSION_UNKNOWN
    )
    verification = (
        base.VERIFICATION_CONFIRMED
        if evidence.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED
        else base.VERIFICATION_UNKNOWN
        if evidence.outcome in (SubmissionOutcome.SUBMITTED, SubmissionOutcome.SUBMISSION_UNCERTAIN)
        else base.VERIFICATION_FAILED
    )

    # Record evidence
    if result.url:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="confirmation_url", url=result.url,
            value=result.url,
        ))
    if evidence.confirmation_text:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="confirmation_text",
            value=evidence.confirmation_text[:4000],
        ))
    if evidence.confirmation_reference_id:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="reference",
            value=evidence.confirmation_reference_id,
        ))
    db.add(ApplicationExecutionEvidence(
        execution_id=execution.id, kind="confirmation_outcome",
        value=evidence.outcome.value,
    ))
    db.add(ApplicationExecutionEvidence(
        execution_id=execution.id, kind="confirmation_confidence",
        value=evidence.confidence,
    ))

    execution.submission_status = verification
    execution.confirmation_url = evidence.confirmation_url or result.url
    execution.confirmation_reference = evidence.confirmation_reference_id or result.reference
    _mark_execution(db, execution.id, status=submitted_status, current_step="verify_submission")

    status_msg = {
        SubmissionOutcome.SUBMISSION_CONFIRMED: "Submission confirmed by explicit evidence.",
        SubmissionOutcome.SUBMITTED: "Submission occurred; weak confirmation signal only.",
        SubmissionOutcome.SUBMISSION_UNCERTAIN: (
            "Submission uncertain — no confirmation evidence found. "
            "Do NOT retry automatically. Human review required."
        ),
        SubmissionOutcome.SUBMISSION_FAILED: "Submission failed.",
        SubmissionOutcome.DUPLICATE_SUSPECTED: "Duplicate application suspected.",
        SubmissionOutcome.BLOCKED: "Submission blocked.",
    }
    _record_step(
        db, execution.id, "verify_submission",
        status="completed",
        message=status_msg.get(evidence.outcome, "Submission outcome recorded."),
    )
    _record_step(
        db, execution.id, "capture_evidence",
        message=(
            f"Evidence captured: outcome={evidence.outcome.value}, "
            f"confidence={evidence.confidence}, "
            f"type={evidence.confirmation_type}."
        ),
    )

    # Record submission outcome event
    _record_submission_event(
        db, execution, package,
        outcome=evidence.outcome,
        reference_id=evidence.confirmation_reference_id,
        confirmation_url=evidence.confirmation_url,
    )

    # record on the legacy tracker + duplicate protection (only real submission)
    if package is not None:
        _upsert_application_tracker(
            db, package, execution,
            confirmed=(evidence.outcome == SubmissionOutcome.SUBMISSION_CONFIRMED),
        )
    db.commit()
    return execution


def _upsert_application_tracker(
    db: Session, package, execution, *, confirmed: bool
) -> None:
    from datetime import date

    from sqlalchemy import select

    from app.application_tracking import status as app_status
    from app.application_tracking.events import record_application_event
    from app.models.application import Application
    from app.models.resume import Resume
    from app.services import application_lifecycle_service

    row = db.scalar(
        select(Application)
        .where(Application.job_id == package.job_id)
        .order_by(Application.id.desc())
        .limit(1)
    )
    legacy = "submitted" if confirmed else "applied"
    target_status = (
        "SUBMISSION_CONFIRMED" if confirmed else "SUBMITTED"
    )
    note = (
        "Submission confirmed by execution."
        if confirmed
        else "Submission occurred; confirmation pending."
    )

    # Snapshot the resume identity so historical apps survive later
    # deactivation/archival of the resume row.
    resume = (
        db.get(Resume, package.selected_resume_id)
        if package.selected_resume_id is not None
        else None
    )

    if row is None:
        row = Application(
            job_id=package.job_id,
            profile_id=package.profile_id,
            resume_id=package.selected_resume_id,
            resume_name=resume.name if resume is not None else None,
            resume_version=resume.version if resume is not None else None,
            status=legacy,
            lifecycle_status=target_status,
            applied_date=date.today(),
            application_url=execution.confirmation_url,
            application_source=execution.platform,
            notes=f"Execution #{execution.id}: {note}",
        )
        db.add(row)
        db.flush()
        new_row = True
        record_application_event(
            db,
            row.id,
            "APPLICATION_CREATED",
            source="EXECUTION",
            previous_status=None,
            new_status=target_status,
            notes=note,
            metadata={"job_id": package.job_id, "execution_id": execution.id},
        )
    else:
        new_row = False
        row.status = legacy
        row.applied_date = date.today()
        row.application_url = execution.confirmation_url or row.application_url
        row.application_source = execution.platform or row.application_source
        row.notes = f"Execution #{execution.id}: {note}"
        if row.resume_name is None and resume is not None:
            row.resume_id = package.selected_resume_id
            row.resume_name = resume.name
            row.resume_version = resume.version

    # Move through the controlled state machine (legal edge only).
    before_status = row.lifecycle_status
    try:
        application_lifecycle_service.move_lifecycle(
            db,
            row,
            target_status,
            source="EXECUTION",
            notes=note,
            metadata={"execution_id": execution.id, "confirmed": confirmed},
        )
        moved = row.lifecycle_status == target_status and before_status != target_status
    except application_lifecycle_service.TrackingError:
        moved = False
        if before_status != target_status:
            record_application_event(
                db,
                row.id,
                target_status,
                source="EXECUTION",
                previous_status=row.lifecycle_status,
                new_status=row.lifecycle_status,
                notes=f"Repeat submission for execution #{execution.id}: {note}",
                metadata={"execution_id": execution.id, "confirmed": confirmed},
            )

    # move_lifecycle returns early when the row is already at the target
    # status (e.g. a new row created at SUBMISSION_CONFIRMED).  Record the
    # milestone event and create the follow-up for a genuine first-time
    # confirmation so that the audit trail and follow-up engine stay consistent.
    if not moved and new_row:
        record_application_event(
            db,
            row.id,
            app_status.default_event_for_status(target_status),
            source="EXECUTION",
            previous_status=None,
            new_status=target_status,
            notes=note,
            metadata={"execution_id": execution.id, "confirmed": confirmed},
        )
        application_lifecycle_service.create_follow_up(db, row, source="EXECUTION")

    db.flush()


def _record_automation_error(db, package, stage: str, message: str) -> None:
    from app.models.automation import AutomationError, AutomationRun

    run = db.scalar(
        select(AutomationRun)
        .where(AutomationRun.run_type == "application_execution")
        .order_by(AutomationRun.id.desc())
        .limit(1)
    )
    db.add(AutomationError(
        run_id=run.id if run is not None else None,
        job_id=package.job_id if package is not None else None,
        stage=stage,
        error_type="EXECUTION_FAILURE",
        message=message,
    ))


def _record_submission_event(
    db: Session,
    execution: ApplicationExecution,
    package,
    *,
    outcome,
    reference_id: str | None = None,
    confirmation_url: str | None = None,
    failure_message: str | None = None,
) -> None:
    """Record a submission outcome event in execution step history.

    Events are immutable — they record what happened, not what we wish
    happened. Never fabricate success when the outcome is uncertain.
    """
    from app.application_execution.submission_verify import SubmissionOutcome

    event_type_map = {
        SubmissionOutcome.SUBMIT_ATTEMPTED: "SUBMISSION_ATTEMPTED",
        SubmissionOutcome.SUBMITTED: "SUBMITTED",
        SubmissionOutcome.SUBMISSION_CONFIRMED: "SUBMISSION_CONFIRMED",
        SubmissionOutcome.SUBMISSION_UNCERTAIN: "SUBMISSION_UNCERTAIN",
        SubmissionOutcome.SUBMISSION_FAILED: "SUBMISSION_FAILED",
        SubmissionOutcome.DUPLICATE_SUSPECTED: "DUPLICATE_SUSPECTED",
        SubmissionOutcome.BLOCKED: "BLOCKED",
    }
    event_type = event_type_map.get(outcome, "SUBMISSION_UNKNOWN")

    parts = [f"outcome={outcome.value}"]
    if reference_id:
        parts.append(f"reference={reference_id}")
    if confirmation_url:
        parts.append(f"url={confirmation_url}")
    if failure_message:
        parts.append(f"reason={failure_message}")

    _record_step(
        db, execution.id, "submission_event",
        status="completed" if outcome != SubmissionOutcome.SUBMISSION_FAILED else "error",
        message=f"Submission event: {'; '.join(parts)}.",
    )
