"""Job lifecycle events (DISCOVERED / UPDATED / REAPPEARED / EXPIRED).

Only the events the pipeline can genuinely observe are written. ``EXPIRED``
is a recognized type but is never auto-emitted from a single missed search.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_sources import normalizer as norm
from app.models.event import JobEvent
from app.models.job import Job

DISCOVERED = "DISCOVERED"
UPDATED = "UPDATED"
REAPPEARED = "REAPPEARED"
EXPIRED = "EXPIRED"

# A listing is considered REAPPEARED only after it was absent for this long.
REAPPEAR_GAP = {
    "days": 1,
}

# Meaningful-job fields that trigger a UPDATED event when they change.
MEANINGFUL_FIELDS = (
    "title",
    "company",
    "location",
    "salary",
    "description",
    "requirements",
    "skills",
    "application_url",
    "posted_date",
)

_EXPIRED_POLICY = (
    "EXPIRED is defined (Phase 4) but never auto-emitted from a single missed "
    "search; repeated misses would need a second source of truth to confirm."
)


def record_event(
    db: Session,
    job_id: int,
    event_type: str,
    event_data: dict[str, Any] | None = None,
    *,
    created_at: datetime | None = None,
) -> JobEvent:
    """Persist one lifecycle event for a job."""
    event = JobEvent(
        job_id=job_id,
        event_type=event_type,
        event_data=event_data or {},
    )
    if created_at is not None:
        event.created_at = created_at
    db.add(event)
    return event


def find_changes(job: Job, record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Diff the meaningful fields between the stored job and a normalized record.

    Returns ``{field: {"before": old, "after": new}}`` for fields that changed.
    """
    changes: dict[str, dict[str, Any]] = {}
    for field in MEANINGFUL_FIELDS:
        before = getattr(job, field)
        after = record.get(field)
        if _values_equal(before, after):
            continue
        changes[field] = {"before": before, "after": after}
    return changes


def _values_equal(before: Any, after: Any) -> bool:
    if isinstance(before, list) or isinstance(after, list):
        return _clean_list(before) == _clean_list(after)
    return _clean_value(before) == _clean_value(after)


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    return norm.clean_text(value)


def _clean_list(value: Any) -> list[str]:
    if not value:
        return []
    items = [norm.clean_text(item) for item in value]
    return [item for item in items if item]


def is_reappeared(job: Job, now: datetime | None = None) -> bool:
    """True when some real gap elapsed between the last sighting and now."""
    if job.last_seen_at is None:
        return False
    clock = now or datetime.now(timezone.utc)
    gap = clock - job.last_seen_at
    return gap.days >= REAPPEAR_GAP["days"]


def recent_events(db: Session, job_id: int, limit: int = 10) -> list[JobEvent]:
    stmt = (
        select(JobEvent)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.desc(), JobEvent.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
