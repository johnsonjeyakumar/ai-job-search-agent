"""Lifecycle helpers for automation run logging."""
from __future__ import annotations

import traceback as _traceback
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.automation import AutomationError, AutomationRun

RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
PARTIAL = "PARTIAL"
FAILED = "FAILED"


def start_run(
    db: Session, run_type: str, source: str, details: dict | None = None
) -> AutomationRun:
    run = AutomationRun(
        run_type=run_type,
        job_source=source,
        status=RUNNING,
        details=details or {},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(
    db: Session,
    run: AutomationRun,
    *,
    status: str,
    jobs_found: int,
    jobs_inserted: int,
    duplicates: int,
    invalid: int,
    message: str | None = None,
) -> AutomationRun:
    details = dict(run.details or {})
    details.update(
        {
            "discovered": jobs_found,
            "inserted": jobs_inserted,
            "duplicates": duplicates,
            "invalid": invalid,
            "message": message,
        }
    )
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.jobs_found = jobs_found
    run.jobs_processed = jobs_inserted
    run.details = details
    db.commit()
    db.refresh(run)
    return run


def record_error(
    db: Session,
    *,
    run_id: int,
    stage: str,
    error_type: str,
    message: str,
    job_id: int | None = None,
    exc: BaseException | None = None,
) -> AutomationError:
    traceback_text = None
    if exc is not None:
        traceback_text = "".join(
            _traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
    error = AutomationError(
        run_id=run_id,
        job_id=job_id,
        stage=stage,
        error_type=error_type[:255],
        message=message[:4000],
        traceback=traceback_text,
    )
    db.add(error)
    db.commit()
    db.refresh(error)
    return error


def get_run(db: Session, run_id: int) -> AutomationRun | None:
    return db.scalar(select(AutomationRun).where(AutomationRun.id == run_id))


def list_recent_runs(db: Session, limit: int = 10) -> list[AutomationRun]:
    return list(
        db.scalars(
            select(AutomationRun).order_by(AutomationRun.id.desc()).limit(limit)
        )
    )
