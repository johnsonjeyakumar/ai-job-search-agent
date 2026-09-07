"""Execution runner (Phase 7).

Turns an APPROVED package into a controlled apply attempt. The runner is the
only place that drives a browser driver, and it does so strictly through the
operations the platform adapter allowed for the resolved mode:

1. preflight (package valid, no duplicate, budget OK)
2. open the application URL
3. stop for login / CAPTCHA instead of fighting them
4. inspect the form, map fields deterministically
5. fill only KNOWN fields, upload only the approved resume
6. stop for any NEW QUESTION or ambiguous required field
7. hand the browser state over at the human approval boundary

Submission happens later (``submit_execution``) and only after explicit user
approval, then verification evidence decides SUBMITTED vs CONFIRMED vs UNKNOWN.
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

        if driver.detect_login():
            _mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                            current_step="open")
            _record_step(db, execution.id, "open", status="warning",
                         message="Login required. Complete it manually; execution "
                                 "continues afterwards (credentials are never stored).")
            db.commit()
            return execution

        ctx = build_profile_context(profile, prefs, answers)

        _record_step(db, execution.id, "inspect_form", status="running")
        detected = driver.inspect_form()
        _record_step(db, execution.id, "inspect_form",
                     message=f"Detected {len(detected)} form fields.")

        _record_step(db, execution.id, "map_fields", status="running")
        mapped = map_fields(detected, ctx)
        for warning in mapped.warnings:
            _add_warning(db, execution.id, "map_fields", warning)
        _record_step(
            db, execution.id, "map_fields",
            message=f"Mapped {len(mapped.fields)} fields, "
                    f"{len(mapped.new_questions)} new questions.",
        )

        # -- resume upload ----------------------------------------------------
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

        # -- fill known fields ------------------------------------------------
        fills: list[dict] = []
        fields_filled = 0
        if adapter.allows_fill_known(mode):
            for f in mapped.fields:
                if f.classification != base.KNOWN or f.detected.kind == "file":
                    continue
                if f.matched_key == "answer":
                    mapped.answered_questions = getattr(mapped, "answered_questions", 0) + 1
                result = driver.fill(f.detected.key, f.value or "")
                fills.append(
                    {"field_key": f.detected.key, "label": f.detected.label, "value": f.value or ""}
                )
                if result.status == base.KNOWN:
                    fields_filled += 1
                else:
                    _add_warning(db, execution.id, "fill_fields",
                                 f"'{f.detected.label}' fill failed: {result.message}")
        _record_step(db, execution.id, "fill_fields",
                     message=f"Filled {fields_filled} known fields.")

        # -- validate form ----------------------------------------------------
        required_unfilled = [
            f for f in mapped.fields
            if f.detected.required and f.classification != base.KNOWN
        ]
        new_questions = mapped.new_questions
        for q in new_questions:
            _add_warning(db, execution.id, "validate_form",
                         f"NEW QUESTION DETECTED: '{q.label}'.")

        fatal = []
        fatal.extend(
            f"Required field '{f.detected.label}' needs review ({f.ambiguity})."
            for f in required_unfilled
            if f.matched_key != "answer"
        )
        if new_questions and not mapped.unknown_required:
            fatal.append("A new question was detected that no prepared answer covers.")

        # answers must still be valid
        invalid = _invalid_answers(answers)
        if invalid:
            fatal.append(f"Package answers are invalid for: {', '.join(invalid[:3])}.")

        summary = {
            "fields_detected": len(detected),
            "fields_filled": fields_filled,
            "fields_needing_review": mapped.review_count + len(required_unfilled),
            "answered_questions": sum(1 for f in mapped.fields if f.matched_key == "answer"),
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
            "fields_needing_review": mapped.review_count + len(required_unfilled),
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
    from app.models.application import Application
    from app.models.application_execution import ApplicationExecution

    prev_application = db.scalar(
        select(Application)
        .where(Application.job_id == package.job_id)
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if prev_application is not None and prev_application.status in base.LOGGED_IN_STATUSES:
        return (
            f"A submission for this job is already tracked "
            f"(application #{prev_application.id}, status '{prev_application.status}'). "
            "Execution blocked to avoid a duplicate application."
        )

    prior = db.scalar(
        select(ApplicationExecution)
        .where(ApplicationExecution.package_id == package.id)
        .where(ApplicationExecution.status.in_(base._EXTERNAL_ACTION_STATUSES))
        .order_by(ApplicationExecution.id.desc())
        .limit(1)
    )
    if prior is not None:
        return (
            f"A prior execution (run #{prior.id}) already ended in "
            f"'{prior.status}' for this package. Execution blocked to avoid "
            "a duplicate application."
        )
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
        # replay the known (safe) fills from the approval step.
        for item in fills:
            key = item.get("field_key")
            value = item.get("value") or ""
            if not key:
                continue
            driver.fill(key, value)
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
        db.commit()
        return execution

    # submission actually happened; decide confirmation status by evidence
    submitted_status = (
        base.STATUS_SUBMISSION_CONFIRMED
        if result.confirmed
        else base.STATUS_SUBMISSION_UNKNOWN
    )
    verification = (
        base.VERIFICATION_CONFIRMED if result.confirmed else base.VERIFICATION_UNKNOWN
    )
    if result.url:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="confirmation_url", url=result.url,
            value=result.url,
        ))
    if result.confirmed:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="confirmation_text",
            value=(result.raw_text or result.message or "")[:4000],
        ))
    if result.reference:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="reference", value=result.reference,
        ))

    execution.submission_status = verification
    if result.confirmed:
        execution.confirmation_url = result.url
    execution.confirmation_reference = result.reference
    _mark_execution(db, execution.id, status=submitted_status, current_step="verify_submission")
    _record_step(db, execution.id, "verify_submission",
                 status="completed",
                 message=(
                     "Submission confirmed by explicit evidence."
                     if result.confirmed
                     else "Submission occurred but no confirmation evidence was found."
                 ))
    _record_step(db, execution.id, "capture_evidence",
                 message="Evidence captured (confirmation markers).")

    # record on the legacy tracker + duplicate protection (only real submission)
    if package is not None:
        _upsert_application_tracker(db, package, execution, confirmed=result.confirmed)
    db.commit()
    return execution


def _upsert_application_tracker(
    db: Session, package, execution, *, confirmed: bool
) -> None:
    from datetime import date

    from sqlalchemy import select

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
            lifecycle_status="DISCOVERED",
            applied_date=date.today(),
            application_url=execution.confirmation_url,
            application_source=execution.platform,
            notes=f"Execution #{execution.id}: {note}",
        )
        db.add(row)
        db.flush()
        record_application_event(
            db,
            row.id,
            "APPLICATION_CREATED",
            source="EXECUTION",
            previous_status=None,
            new_status="DISCOVERED",
            notes=note,
            metadata={"job_id": package.job_id, "execution_id": execution.id},
        )
    else:
        row.status = legacy
        row.applied_date = date.today()
        row.application_url = execution.confirmation_url or row.application_url
        row.application_source = execution.platform or row.application_source
        row.notes = f"Execution #{execution.id}: {note}"
        if row.resume_name is None and resume is not None:
            row.resume_id = package.selected_resume_id
            row.resume_name = resume.name
            row.resume_version = resume.version

    # Move through the controlled state machine (legal edge only); record a
    # transparent history marker if the row is already beyond SUBMITTED (e.g.
    # a repeat submission after a response) instead of silently corrupting it.
    try:
        application_lifecycle_service.move_lifecycle(
            db,
            row,
            target_status,
            source="EXECUTION",
            notes=note,
            metadata={"execution_id": execution.id, "confirmed": confirmed},
        )
    except application_lifecycle_service.TrackingError:
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
    # Reference mirror of the state machine helpers for clarity (no-op).
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
