from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.resume import Resume
from app.schemas.resume import ResumeUpdate
from app.storage.base import FileStorage
from app.storage.local import new_key


def list_resumes(db: Session) -> list[Resume]:
    return list(db.scalars(select(Resume).order_by(Resume.created_at.desc())))


def get_resume(db: Session, resume_id: int) -> Resume | None:
    return db.get(Resume, resume_id)


def _activate_exclusive(db: Session, resume: Resume) -> None:
    """Only one resume is active at a time."""
    if not resume.is_active:
        return
    db.flush()  # ensure resume.id is generated so it is excluded below
    for other in db.scalars(
        select(Resume).where(Resume.id != resume.id, Resume.is_active.is_(True))
    ):
        other.is_active = False


def create_resume(
    db: Session,
    *,
    name: str,
    target_role: str | None,
    version: str | None,
    is_active: bool,
    data: bytes,
    content_type: str,
    file_name: str,
    storage: FileStorage,
    profile_id: int | None = None,
) -> Resume:
    stored_path = storage.save(data, new_key(file_name))
    resume = Resume(
        name=name,
        target_role=target_role,
        version=version,
        is_active=is_active,
        file_path=str(stored_path),
        file_name=file_name,
        file_size=len(data),
        content_type=content_type,
        profile_id=profile_id,
    )
    db.add(resume)
    _activate_exclusive(db, resume)
    db.commit()
    db.refresh(resume)
    return resume


def update_resume(db: Session, resume: Resume, data: ResumeUpdate) -> Resume:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(resume, field, value)
    _activate_exclusive(db, resume)
    db.commit()
    db.refresh(resume)
    return resume


def replace_resume_file(
    db: Session,
    resume: Resume,
    *,
    data: bytes,
    content_type: str,
    file_name: str,
    storage: FileStorage,
) -> Resume:
    if resume.file_path:
        try:
            storage.delete(resume.file_path)
        except OSError:
            pass
    stored_path = storage.save(data, new_key(file_name))
    resume.file_path = str(stored_path)
    resume.file_name = file_name
    resume.file_size = len(data)
    resume.content_type = content_type
    db.commit()
    db.refresh(resume)
    return resume


def delete_resume(db: Session, resume: Resume, storage: FileStorage) -> None:
    if resume.file_path:
        try:
            storage.delete(resume.file_path)
        except OSError:
            pass
    db.delete(resume)
    db.commit()
