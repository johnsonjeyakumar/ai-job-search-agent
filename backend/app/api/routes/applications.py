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
from app.services import application_package_service as service

router = APIRouter(prefix="/applications", tags=["applications"])


def _to_summary(db: Session, package) -> PackageSummary:
    return PackageSummary.model_validate(service.summary_row(db, package))


def _handle(e: Exception) -> HTTPException:
    if isinstance(e, service.PackageNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, (service.DuplicatePackageError, service.PackageNotApprovableError)):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=500, detail=str(e))


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
