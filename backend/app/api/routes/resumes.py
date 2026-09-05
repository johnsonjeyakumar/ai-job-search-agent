from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.session import get_db
from app.schemas.resume import ResumeRead, ResumeUpdate
from app.services import resume_service
from app.storage.base import FileStorage
from app.storage.local import LocalFileStorage
from app.storage.validation import UploadValidationError, validate_upload

router = APIRouter(prefix="/resumes", tags=["resumes"])


def get_file_storage() -> FileStorage:
    return LocalFileStorage()


def _read_uploaded_file(file: UploadFile | None) -> bytes:
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A resume file is required.",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The uploaded file is empty.",
        )
    return data


def _validated_upload(file: UploadFile) -> tuple[bytes, str, str]:
    data = _read_uploaded_file(file)
    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    try:
        safe_name, _ = validate_upload(
            file.filename or "", file.content_type or "", data, max_bytes
        )
    except UploadValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return data, safe_name, (file.content_type or "").split(";")[0].strip()


@router.get("", response_model=list[ResumeRead])
def list_resumes(db: Session = Depends(get_db)) -> list[ResumeRead]:
    return resume_service.list_resumes(db)


@router.post("", response_model=ResumeRead)
def create_resume(
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=255),
    target_role: str | None = Form(default=None),
    version: str | None = Form(default=None),
    is_active: bool = Form(default=True),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_file_storage),
) -> ResumeRead:
    data, safe_name, content_type = _validated_upload(file)
    return resume_service.create_resume(
        db,
        name=name.strip(),
        target_role=target_role,
        version=version,
        is_active=is_active,
        data=data,
        content_type=content_type,
        file_name=safe_name,
        storage=storage,
    )


@router.get("/{resume_id}", response_model=ResumeRead)
def read_resume(resume_id: int, db: Session = Depends(get_db)) -> ResumeRead:
    resume = resume_service.get_resume(db, resume_id)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found."
        )
    return resume


@router.put("/{resume_id}", response_model=ResumeRead)
def update_resume(
    resume_id: int, payload: ResumeUpdate, db: Session = Depends(get_db)
) -> ResumeRead:
    resume = resume_service.get_resume(db, resume_id)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found."
        )
    return resume_service.update_resume(db, resume, payload)


@router.post("/{resume_id}/file", response_model=ResumeRead)
def replace_resume_file(
    resume_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_file_storage),
) -> ResumeRead:
    resume = resume_service.get_resume(db, resume_id)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found."
        )
    data, safe_name, content_type = _validated_upload(file)
    return resume_service.replace_resume_file(
        db,
        resume,
        data=data,
        content_type=content_type,
        file_name=safe_name,
        storage=storage,
    )


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(
    resume_id: int,
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_file_storage),
) -> None:
    resume = resume_service.get_resume(db, resume_id)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found."
        )
    resume_service.delete_resume(db, resume, storage)
