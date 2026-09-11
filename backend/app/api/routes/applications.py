from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.application_package import (
    AnswerRead,
    AnswerUpdateRequest,
    ApplicationPrepareRequest,
    CoverLetterUpdateRequest,
    PackageActionResponse,
    PackagePrepareResponse,
    PackageSummary,
)
from app.schemas.execution import (
    CancelExecutionRequest,
    ConfirmSubmissionRequest,
    ExecuteRequest,
)
from app.services import application_execution_service as exec_service
from app.services import application_package_service as service

router = APIRouter(prefix="/applications", tags=["applications"])


def _to_summary(db: Session, package) -> PackageSummary:
    return PackageSummary.model_validate(service.summary_row(db, package))


def _handle(e: Exception) -> HTTPException:
    if isinstance(e, service.PackageNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, (service.DuplicatePackageError, service.PackageNotApprovableError)):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=500, detail="Internal server error.")


@router.get("", response_model=list[PackageSummary])
def list_packages(
    status: str | None = Query(default=None),
    include_history: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[PackageSummary]:
    packages = service.list_packages(db, status=status, include_history=include_history)
    return [_to_summary(db, p) for p in packages]


@router.post("/prepare", response_model=PackagePrepareResponse)
async def prepare(
    payload: ApplicationPrepareRequest, db: Session = Depends(get_db)
) -> PackagePrepareResponse:
    try:
        package = await service.prepare_package(
            db,
            payload.job_id,
            include_cover_letter=payload.include_cover_letter,
        )
    except service.PackageNotFoundError as exc:
        raise _handle(exc) from exc
    except service.DuplicatePackageError as exc:
        existing = service._existing_package(db, payload.job_id)
        if existing is None:
            raise _handle(exc) from exc
        return PackagePrepareResponse(
            package=_to_summary(db, existing),
            duplicate_disclaimer=str(exc),
            created=False,
        )
    return PackagePrepareResponse(
        package=_to_summary(db, package),
        duplicate_disclaimer=package.duplicate_disclaimer,
        created=True,
    )


@router.get("/{package_id}", response_model=PackageSummary)
def get_package(package_id: int, db: Session = Depends(get_db)) -> PackageSummary:
    package = service.get_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"Package {package_id} not found")
    return _to_summary(db, package)


@router.get("/{package_id}/preview")
def preview_package(package_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return service.preview_package(db, package_id)
    except service.PackageNotFoundError as exc:
        raise _handle(exc) from exc


@router.post("/{package_id}/validate", response_model=PackageActionResponse)
def validate_package(package_id: int, db: Session = Depends(get_db)) -> PackageActionResponse:
    try:
        package = service.validate_package(db, package_id)
    except service.PackageNotFoundError as exc:
        raise _handle(exc) from exc
    return PackageActionResponse(
        package=_to_summary(db, package),
        message=package.quality_gate_summary or "Revalidation complete.",
    )


@router.post("/{package_id}/regenerate", response_model=PackagePrepareResponse)
async def regenerate_package(
    package_id: int, db: Session = Depends(get_db)
) -> PackagePrepareResponse:
    try:
        package = await service.regenerate_package(db, package_id)
    except (service.PackageNotFoundError, service.DuplicatePackageError) as exc:
        raise _handle(exc) from exc
    return PackagePrepareResponse(
        package=_to_summary(db, package),
        duplicate_disclaimer=package.duplicate_disclaimer,
        created=True,
    )


@router.post("/{package_id}/approve", response_model=PackageActionResponse)
def approve_package(package_id: int, db: Session = Depends(get_db)) -> PackageActionResponse:
    try:
        package = service.approve_package(db, package_id)
    except (service.PackageNotFoundError, service.PackageNotApprovableError) as exc:
        raise _handle(exc) from exc
    return PackageActionResponse(
        package=_to_summary(db, package),
        message="Approved for execution. Nothing has been submitted.",
    )


@router.post("/{package_id}/archive", response_model=PackageActionResponse)
def archive_package(package_id: int, db: Session = Depends(get_db)) -> PackageActionResponse:
    try:
        package = service.archive_package(db, package_id)
    except service.PackageNotFoundError as exc:
        raise _handle(exc) from exc
    return PackageActionResponse(
        package=_to_summary(db, package),
        message="Package archived.",
    )


@router.put("/{package_id}/answers/{answer_id}", response_model=AnswerRead)
def update_answer(
    package_id: int,
    answer_id: int,
    payload: AnswerUpdateRequest,
    db: Session = Depends(get_db),
) -> AnswerRead:
    try:
        answer = service.update_answer(db, package_id, answer_id, payload.answer_text)
    except (service.PackageNotFoundError, service.PackageNotApprovableError) as exc:
        raise _handle(exc) from exc
    return AnswerRead.model_validate(answer)


@router.put("/{package_id}/cover-letter", response_model=PackageSummary)
def update_cover_letter(
    package_id: int,
    payload: CoverLetterUpdateRequest,
    db: Session = Depends(get_db),
) -> PackageSummary:
    try:
        package = service.update_cover_letter(db, package_id, payload.text)
    except service.PackageNotFoundError as exc:
        raise _handle(exc) from exc
    return _to_summary(db, package)


# ---------------------------------------------------------------------------
# Phase 7: application execution
# ---------------------------------------------------------------------------


def _execution_or_404(package_id: int, db: Session, execution_id: int):
    execution = exec_service.get_execution(db, execution_id)
    if execution is None or execution.package_id != package_id:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found.")
    return execution


@router.get("/{package_id}/execution")
def get_execution(package_id: int, db: Session = Depends(get_db)) -> dict:
    package = service.get_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"Package {package_id} not found")
    execution = exec_service.latest_execution(db, package_id)
    if execution is None:
        return {
            "preview": exec_service.preview_execution(db, package),
            "execution": None,
        }
    return {
        "preview": exec_service.preview_execution(db, package),
        "execution": exec_service.serialize_execution(db, execution),
    }


@router.get("/{package_id}/execution/budget")
def get_execution_budget(package_id: int, db: Session = Depends(get_db)) -> dict:
    if service.get_package(db, package_id) is None:
        raise HTTPException(status_code=404, detail=f"Package {package_id} not found")
    return {"budget": exec_service.daily_budget(db)}


@router.post("/{package_id}/execute")
def execute(
    package_id: int,
    payload: ExecuteRequest,
    db: Session = Depends(get_db),
) -> dict:
    package = service.get_package(db, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=f"Package {package_id} not found")
    try:
        execution = exec_service.start_execution(
            db,
            package,
            driver=payload.driver,
            force_duplicate=payload.force_duplicate,
        )
    except Exception as exc:
        raise _handle_exec_error(exc) from exc
    return {
        "execution": exec_service.serialize_execution(db, execution),
        "message": _execution_message(execution),
    }


@router.post("/{package_id}/execution/{execution_id}/approve")
def approve_execution(
    package_id: int,
    execution_id: int,
    db: Session = Depends(get_db),
) -> dict:
    _execution_or_404(package_id, db, execution_id)
    try:
        execution = exec_service.approve_execution(db, execution_id)
    except exec_service.ExecutionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "execution": exec_service.serialize_execution(db, execution),
        "message": _execution_message(execution),
    }


@router.post("/{package_id}/execution/{execution_id}/cancel")
def cancel_execution(
    package_id: int,
    execution_id: int,
    payload: CancelExecutionRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    _execution_or_404(package_id, db, execution_id)
    try:
        execution = exec_service.cancel_execution(db, execution_id)
    except exec_service.ExecutionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "execution": exec_service.serialize_execution(db, execution),
        "message": "Execution cancelled. Nothing was submitted.",
    }


@router.post("/{package_id}/execution/{execution_id}/resume")
def resume_execution(
    package_id: int,
    execution_id: int,
    payload: ExecuteRequest,
    db: Session = Depends(get_db),
) -> dict:
    _execution_or_404(package_id, db, execution_id)
    package = service.get_package(db, package_id)
    try:
        execution = exec_service.resume_execution(
            db, package, driver=payload.driver, force_duplicate=payload.force_duplicate
        )
    except Exception as exc:
        raise _handle_exec_error(exc) from exc
    return {
        "execution": exec_service.serialize_execution(db, execution),
        "message": _execution_message(execution),
    }


@router.post("/{package_id}/execution/{execution_id}/confirm")
def confirm_execution(
    package_id: int,
    execution_id: int,
    payload: ConfirmSubmissionRequest,
    db: Session = Depends(get_db),
) -> dict:
    _execution_or_404(package_id, db, execution_id)
    try:
        execution = exec_service.confirm_execution(
            db,
            execution_id,
            verification=payload.verification,
            reference=payload.reference,
            url=payload.url,
            note=payload.note,
        )
    except exec_service.ExecutionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "execution": exec_service.serialize_execution(db, execution),
        "message": _execution_message(execution),
    }


def _handle_exec_error(exc: Exception) -> HTTPException:
    from app.application_execution import base as exec_base

    if isinstance(exc, exec_base.ExecutionBlockedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, exec_service.ExecutionServiceError):
        return HTTPException(status_code=exc.status_code, detail=exc.message)
    return HTTPException(status_code=500, detail="Internal server error.")


def _execution_message(execution) -> str:
    try:
        payload = execution.approval_payload or {}
    except Exception:  # noqa: BLE001
        payload = {}
    action = payload.get("recommended_action")
    if execution.status == "AWAITING_APPROVAL":
        return (
            "APPLICATION READY FOR SUBMISSION — review the summary and approve "
            "to submit (or finish manually)."
        )
    if execution.status == "AWAITING_USER":
        if action == "review_question":
            return "NEW QUESTION DETECTED — review the question before continuing."
        if action == "review_unknown":
            return "Required fields need manual completion."
        if action == "complete_manually":
            return "Complete the remaining steps manually, then confirm the outcome."
        return "Execution paused — action required (login/verification)."
    if execution.status == "BLOCKED":
        return "Execution blocked. Human action required."
    if execution.status == "SUBMISSION_CONFIRMED":
        return "Submission confirmed by explicit evidence."
    if execution.status == "SUBMISSION_UNKNOWN":
        return "Submission occurred; confirmation pending."
    if execution.status == "SUBMITTED":
        return "Submission was marked by the user."
    if execution.status == "EXECUTION_FAILED":
        return "Execution failed — captured errors recorded."
    if execution.status == "CANCELLED":
        return "Execution cancelled."
    return "Execution started."
