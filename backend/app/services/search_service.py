"""Discovery orchestrator: preferences -> source -> store -> run log."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.job_sources import JobSourceError, job_source_registry
from app.job_sources.apify import ApifyJobSource
from app.models.automation import AutomationRun
from app.schemas.preferences import PreferencesUpdate
from app.services import automation_service as run_log
from app.services import job_service
from app.services.preferences_service import get_preferences

logger = logging.getLogger(__name__)


def run_discovery(
    db: Session,
    run_id: int,
    source_name: str = "apify",
    overrides: dict[str, Any] | None = None,
) -> AutomationRun:
    """Execute a full discovery run inside ``db`` (own session in background)."""
    run = run_log.get_run(db, run_id)
    if run is None:
        return None

    try:
        preferences = _effective_preferences(db, overrides or {})
        source = _get_source(source_name)
        limit = (overrides or {}).get("limit")
        result = source.search_jobs(preferences, limit=limit)
    except Exception as exc:  # noqa: BLE001 - any failure must be logged
        run_log.record_error(
            db,
            run_id=run_id,
            stage="discovery",
            error_type=type(exc).__name__,
            message=str(exc) or repr(exc),
            exc=exc,
        )
        run_log.finish_run(
            db,
            run,
            status=run_log.FAILED,
            jobs_found=0,
            jobs_inserted=0,
            duplicates=0,
            invalid=0,
            message=f"Search failed: {exc}",
        )
        logger.exception("Discovery run %s failed", run_id)
        return run

    if result.error:
        run_log.record_error(
            db,
            run_id=run_id,
            stage="discovery",
            error_type="JobSourceError",
            message=result.error,
        )
        run_log.finish_run(
            db,
            run,
            status=run_log.FAILED,
            jobs_found=result.raw_count,
            jobs_inserted=0,
            duplicates=0,
            invalid=len(result.invalid),
            message=result.error,
        )
        return run

    insert = job_service.insert_jobs(db, result.jobs, source=source_name)

    for inv in insert.invalid:
        run_log.record_error(
            db,
            run_id=run_id,
            stage="validate",
            error_type="ValidationError",
            message=f"{inv.get('reason')}: {inv.get('record', {}).get('title')}",
        )
    for inv in result.invalid:
        run_log.record_error(
            db,
            run_id=run_id,
            stage="validate",
            error_type="InvalidRecord",
            message=f"{inv.get('reason')}",
        )

    invalid_total = len(result.invalid) + len(insert.invalid)
    status = run_log.COMPLETED
    if insert.duplicates or insert.inserted:
        if invalid_total:
            status = run_log.PARTIAL
    else:
        status = run_log.COMPLETED if not invalid_total else run_log.PARTIAL

    run_log.finish_run(
        db,
        run,
        status=status,
        jobs_found=result.raw_count,
        jobs_inserted=insert.inserted,
        duplicates=insert.duplicates,
        invalid=invalid_total,
        message="Discovery completed",
    )
    return run


def _effective_preferences(
    db: Session, overrides: dict[str, Any]
) -> dict[str, Any]:
    saved = get_preferences(db)
    base = PreferencesUpdate().model_dump()
    if saved is not None:
        base.update(
            {key: getattr(saved, key) for key in base if hasattr(saved, key)}
        )
    if overrides.get("locations"):
        base["preferred_locations"] = overrides["locations"]
    if overrides.get("roles"):
        base["target_roles"] = overrides["roles"]
    return base


def _get_source(name: str):
    if name == "apify":
        return ApifyJobSource()
    create = job_source_registry.get(name)
    if create is None:
        raise JobSourceError(f"Unknown job source: {name}")
    return create()
