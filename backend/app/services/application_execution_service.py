"""Application execution orchestration (Phase 7).

API-facing layer: daily budget, preview, start / approve / cancel / resume /
confirm, and the read model serialization. All safety decisions live in the
execution engine; this layer only translates between HTTP and the engine.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application_execution import base, executor
from app.application_execution.adapters import get_adapter
from app.application_execution.detector import detect_platform
from app.models.application_execution import (
    ApplicationExecution,
    ApplicationExecutionEvidence,
    ApplicationExecutionStep,
)
from app.models.automation import AutomationRun
from app.models.preferences import Preferences

SUBMIT_STATUSES = (
    base.STATUS_SUBMITTED,
    base.STATUS_SUBMISSION_CONFIRMED,
    base.STATUS_SUBMISSION_UNKNOWN,
)


class ExecutionServiceError(Exception):
    """Generic failure carrying an HTTP-ish detail."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def get_execution(db: Session, execution_id: int) -> ApplicationExecution | None:
    return db.get(ApplicationExecution, execution_id)


def latest_execution(db: Session, package_id: int) -> ApplicationExecution | None:
    return db.scalar(
        select(ApplicationExecution)
        .where(ApplicationExecution.package_id == package_id)
        .order_by(ApplicationExecution.id.desc())
        .limit(1)
    )


def _get_preferences(db: Session) -> Preferences | None:
    return db.scalar(select(Preferences).order_by(Preferences.id).limit(1))


def daily_budget(db: Session) -> dict:
    """{target, maximum, used_today} for the current local day."""
    prefs = _get_preferences(db)
    start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = len(
        list(
            db.scalars(
                select(ApplicationExecution.id)
                .where(ApplicationExecution.status.in_(SUBMIT_STATUSES))
                .where(ApplicationExecution.started_at >= start_of_day)
            )
        )
    )
    return {
        "target": prefs.daily_application_target if prefs is not None else None,
        "maximum": prefs.daily_application_maximum if prefs is not None else None,
        "used_today": used_today,
    }


def detect_for_package(db: Session, package) -> dict:
    """Deterministic detection + policy preview (no browser involved)."""
    from app.services import job_service

    job = job_service.get_job(db, package.job_id)
    prefs = _get_preferences(db)
    if job is None:
        return {"platform": "generic", "mode": base.HUMAN_ASSISTED, "url": None,
                "configured_mode": base.HUMAN_ASSISTED, "policy_reason": "Job missing."}
    detection = detect_platform(
        url=job.url, application_url=job.application_url, source=job.source
    )
    adapter = get_adapter(detection.platform)
    policy = adapter.policy(
        dict(getattr(prefs, "platform_policies", None) or {}) if prefs is not None else {}
    )
    return {
        "platform": detection.platform,
        "platform_label": detection.label,
        "mode": policy.mode,
        "configured_mode": dict(getattr(prefs, "platform_policies", None) or {})
        if prefs is not None
        else {},
        "policy_reason": policy.reason,
        "auto_submit_allowed": policy.supports_automated_submit,
        "url": job.application_url or job.url,
        "based_on": detection.based_on,
        "career_site": detection.career_site,
    }


def preview_execution(db: Session, package) -> dict:
    """Execution preview surfaced BEFORE any external interaction."""
    from app.services import job_service

    job = job_service.get_job(db, package.job_id)
    det = detect_for_package(db, package)
    budget = daily_budget(db)
    warnings: list[str] = []
    if package.status != "APPROVED":
        warnings.append(f"Package is '{package.status}', not APPROVED.")
    if package.quality_gate == "FAIL":
        warnings.append("Package failed validation.")
    if det.get("mode") == base.UNSUPPORTED:
        warnings.append("Platform policy is UNSUPPORTED; inspection only.")
    max_budget = budget.get("maximum")
    if max_budget is not None and budget.get("used_today", 0) >= max_budget:
        warnings.append("Daily application maximum already reached.")
    return {
        "package_id": package.id,
        "package_version": package.version,
        "package_status": package.status,
        "quality_gate": package.quality_gate,
        "job": {
            "title": job.title if job else None,
            "company": job.company if job else None,
            "url": job.application_url or job.url if job else None,
        },
        "platform": det,
        "budget": budget,
        "warnings": warnings,
    }


def start_execution(
    db: Session,
    package,
    *,
    driver: str = "auto",
    force_duplicate: bool = False,
) -> ApplicationExecution:
    """Run the safe stage of execution (never submission)."""
    budget = daily_budget(db)
    execution = executor.run_execution(
        db,
        package,
        driver_name=driver,
        force_duplicate=force_duplicate,
        budget=budget,
        headless=True,
    )
    _record_run(db, execution)
    db.refresh(execution)
    return execution


def _record_run(db: Session, execution: ApplicationExecution) -> None:
    status = {
        base.STATUS_BLOCKED: "blocked",
        base.STATUS_EXECUTION_FAILED: "failed",
        base.STATUS_SUBMISSION_CONFIRMED: "succeeded",
        base.STATUS_SUBMITTED: "succeeded",
        base.STATUS_SUBMISSION_UNKNOWN: "succeeded",
    }.get(execution.status, "running")
    db.add(
        AutomationRun(
            run_type="application_execution",
            job_source=execution.platform,
            status=status,
            details={
                "package_id": execution.package_id,
                "execution_id": execution.id,
                "mode": execution.execution_mode,
                "submission_status": execution.submission_status,
            },
        )
    )
    db.commit()


def _revalidate_for_submit(db: Session, package) -> list[str]:
    from app.application_execution.executor import _answers_as_dicts, _invalid_answers

    fatal: list[str] = []
    if package is None:
        return ["Package no longer exists."]
    if package.status != "APPROVED":
        fatal.append(f"Package is '{package.status}', not APPROVED.")
    if package.quality_gate == "FAIL":
        fatal.append("Package failed validation.")
    invalid = _invalid_answers(_answers_as_dicts(db, package.id))
    if invalid:
        fatal.append(f"Answers invalid for: {', '.join(invalid[:3])}.")
    return fatal


def approve_execution(db: Session, execution_id: int) -> ApplicationExecution:
    """Act on the human approval boundary.

    For modes that allow automated submission this performs the actual
    submission (replaying the approved safe steps). For HUMAN_ASSISTED it moves
    the run to AWAITING_USER so the human completes and submits manually.
    """
    from app.models.application_package import ApplicationPackage

    execution = get_execution(db, execution_id)
    if execution is None:
        raise ExecutionServiceError("Execution not found.", 404)
    if execution.status != base.STATUS_AWAITING_APPROVAL:
        raise ExecutionServiceError(
            f"Execution is '{execution.status}', not ready for approval.", 409
        )
    package = db.get(ApplicationPackage, execution.package_id)
    fatal = _revalidate_for_submit(db, package)
    payload = execution.approval_payload or {}
    if fatal:
        executor._mark_execution(db, execution.id, status=base.STATUS_BLOCKED,
                                 current_step="pre_submission_check")
        msg = " ; ".join(fatal)
        executor._record_step(db, execution.id, "pre_submission_check",
                              status="blocked", message=msg)
        db.commit()
        raise ExecutionServiceError(msg, 409)

    mode = execution.execution_mode
    required_unfilled = [
        q for q in (payload.get("required_unfilled") or [])
        if q
    ]
    if required_unfilled:
        executor._mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                                 current_step="approval")
        executor._record_step(db, execution.id, "approval", status="warning",
                              message="Required fields still need manual completion.")
        db.commit()
        return execution

    adapter = get_adapter(execution.platform)
    if not adapter.allows_automated_submit(mode) or mode == base.HUMAN_ASSISTED:
        execution.execution_mode = mode
        executor._mark_execution(db, execution.id, status=base.STATUS_AWAITING_USER,
                                 current_step="approval")
        executor._record_step(db, execution.id, "approval",
                              message="Approval recorded; complete and submit manually, "
                                      "then confirm the outcome.")
        db.commit()
        return execution

    return executor.submit_execution(db, execution)


def cancel_execution(db: Session, execution_id: int) -> ApplicationExecution:
    execution = get_execution(db, execution_id)
    if execution is None:
        raise ExecutionServiceError("Execution not found.", 404)
    if execution.status in base._TERMINAL_STATUSES:
        raise ExecutionServiceError(
            f"Execution already finished as '{execution.status}'.", 409
        )
    executor._mark_execution(db, execution.id, status=base.STATUS_CANCELLED,
                             current_step="cancel")
    executor._record_step(db, execution.id, "cancel",
                          message="Cancelled by the user before submission.")
    db.add(ApplicationExecutionEvidence(
        execution_id=execution.id, kind="user_note",
        value="Execution cancelled by the user.",
    ))
    db.commit()
    return execution


def resume_execution(
    db: Session, package, *, driver: str = "auto", force_duplicate: bool = False
) -> ApplicationExecution:
    """Continue a paused/blocked run by starting a fresh safe-stage attempt.

    The previous run stays recorded; this creates a new attempt row for the
    same package so history is preserved while the user gets a live browser.
    """
    return start_execution(
        db, package, driver=driver, force_duplicate=force_duplicate
    )


def confirm_execution(
    db: Session,
    execution_id: int,
    *,
    verification: str,
    reference: str | None = None,
    url: str | None = None,
    note: str | None = None,
) -> ApplicationExecution:
    """Record a HUMAN-ATTESTED manual submission for HUMAN_ASSISTED runs.

    This is the only way a human-assisted run reaches SUBMITTED/CONFIRMED: the
    user states what actually happened after submitting by hand. Confirmation
    evidence is stored with the run.
    """
    from app.models.application_package import ApplicationPackage

    execution = get_execution(db, execution_id)
    if execution is None:
        raise ExecutionServiceError("Execution not found.", 404)
    if execution.status not in (base.STATUS_AWAITING_USER, base.STATUS_AWAITING_APPROVAL):
        raise ExecutionServiceError(
            f"Execution is '{execution.status}'; only a paused run can be confirmed.", 409
        )
    verification = verification.upper()
    if verification not in base.VERIFICATION_RESULTS:
        raise ExecutionServiceError(f"Invalid verification: {verification}", 422)

    confirmed = verification == base.VERIFICATION_CONFIRMED
    final_status = (
        base.STATUS_SUBMISSION_CONFIRMED if confirmed else base.STATUS_SUBMITTED
    )
    execution.submission_status = (
        base.VERIFICATION_CONFIRMED if confirmed
        else base.VERIFICATION_LIKELY if verification == base.VERIFICATION_LIKELY
        else base.VERIFICATION_UNKNOWN
    )
    execution.confirmation_url = url or execution.confirmation_url
    execution.confirmation_reference = reference or execution.confirmation_reference
    executor._mark_execution(db, execution.id, status=final_status,
                             current_step="verify_submission")
    executor._record_step(db, execution.id, "verify_submission",
                          status="completed",
                          message=f"Human-reported outcome ({verification}).")
    db.add(ApplicationExecutionEvidence(
        execution_id=execution.id, kind="user_note",
        value=note or "User confirmed a manual submission.",
        url=url,
    ))
    if reference:
        db.add(ApplicationExecutionEvidence(
            execution_id=execution.id, kind="reference", value=reference,
        ))
    package = db.get(ApplicationPackage, execution.package_id)
    if package is not None and confirmed:
        from app.application_execution.executor import _upsert_application_tracker

        _upsert_application_tracker(db, package, execution, confirmed=confirmed)
    db.commit()
    return execution


def read_steps(db: Session, execution_id: int) -> list[ApplicationExecutionStep]:
    return list(
        db.scalars(
            select(ApplicationExecutionStep)
            .where(ApplicationExecutionStep.execution_id == execution_id)
            .order_by(ApplicationExecutionStep.order, ApplicationExecutionStep.id)
        )
    )


def read_evidence(db: Session, execution_id: int) -> list[ApplicationExecutionEvidence]:
    return list(
        db.scalars(
            select(ApplicationExecutionEvidence)
            .where(ApplicationExecutionEvidence.execution_id == execution_id)
            .order_by(ApplicationExecutionEvidence.id)
        )
    )


def serialize_execution(db: Session, execution: ApplicationExecution) -> dict:
    steps = [
        {
            "id": s.id,
            "step": s.step,
            "order": s.order,
            "status": s.status,
            "message": s.message,
            "url": s.url,
            "started_at": s.started_at,
            "completed_at": s.completed_at,
        }
        for s in read_steps(db, execution.id)
    ]
    evidence = [
        {
            "id": e.id,
            "kind": e.kind,
            "value": e.value,
            "url": e.url,
            "created_at": e.created_at,
        }
        for e in read_evidence(db, execution.id)
    ]
    return {
        "id": execution.id,
        "package_id": execution.package_id,
        "platform": execution.platform,
        "execution_mode": execution.execution_mode,
        "status": execution.status,
        "current_step": execution.current_step,
        "submission_status": execution.submission_status,
        "confirmation_url": execution.confirmation_url,
        "confirmation_reference": execution.confirmation_reference,
        "approval_payload": execution.approval_payload or {},
        "warnings": execution.warnings or [],
        "execution_summary": execution.execution_summary or {},
        "daily_budget": execution.daily_budget or {},
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "created_at": execution.created_at,
        "updated_at": execution.updated_at,
        "steps": steps,
        "evidence": evidence,
    }
