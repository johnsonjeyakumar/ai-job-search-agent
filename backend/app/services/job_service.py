"""Job listing, filtering, pagination, and duplicate-safe insertion (Phase 4).

``insert_jobs`` now also maintains the Phase 4 lifecycle side effects:
freshness/company/quality bookkeeping, DISCOVERED/UPDATED/REAPPEARED events,
and ``first_seen_at``/``last_seen_at``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.job_sources import normalizer as norm
from app.models.job import Job
from app.models.quality import JobQualityScore
from app.services import (
    company_service,
    freshness_service,
    job_events_service,
    job_quality_service,
)


@dataclass
class InsertResult:
    inserted: int
    duplicates: int
    invalid: list[dict[str, Any]]


VALID_SORTS = (
    "discovered",
    "posted",
    "freshness_desc",
    "freshness_asc",
    "quality_desc",
    "quality_asc",
)


def list_jobs(
    db: Session,
    *,
    page: int = 1,
    limit: int = 20,
    role: str | None = None,
    location: str | None = None,
    source: str | None = None,
    remote_type: str | None = None,
    posted_within_days: int | None = None,
    company: str | None = None,
    freshness: str | None = None,
    sort: str = "discovered",
) -> tuple[list[Job], int]:
    page = max(1, page)
    limit = min(max(1, limit), 100)

    conditions = []
    if role:
        pattern = f"%{role}%"
        conditions.append(func.lower(Job.title).like(func.lower(pattern)))
    if location:
        pattern = f"%{location}%"
        conditions.append(func.lower(Job.location).like(func.lower(pattern)))
    if source:
        conditions.append(Job.source == source)
    if remote_type:
        conditions.append(func.lower(Job.remote_type) == remote_type.lower())
    if posted_within_days:
        cutoff = datetime.now().date() - timedelta(days=posted_within_days)
        conditions.append(
            or_(Job.posted_date >= cutoff, Job.posted_date.is_(None))
        )
    if company:
        pattern = f"%{company}%"
        conditions.append(func.lower(Job.company).like(func.lower(pattern)))
    if freshness:
        window = freshness_service.freshness_filter(
            freshness, Job.posted_date, datetime.now().date()
        )
        if window is None:
            conditions.append(Job.posted_date.is_(None))
        else:
            conditions.extend(window)

    order = _ordering(sort)
    query = select(Job)
    if conditions:
        query = query.where(*conditions)
    query = query.order_by(*order)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(db.scalars(query.offset((page - 1) * limit).limit(limit)))
    return items, total


def _ordering(sort: str):
    if sort not in VALID_SORTS:
        raise ValueError(f"Unsupported sort: {sort}")
    if sort == "discovered":
        return [Job.discovered_date.desc(), Job.id.desc()]
    if sort in ("posted", "freshness_desc"):
        return [
            Job.posted_date.is_(None),
            Job.posted_date.desc(),
            Job.id.desc(),
        ]
    if sort == "freshness_asc":
        return [
            Job.posted_date.is_(None),
            Job.posted_date.asc(),
            Job.id.desc(),
        ]
    score = _current_score_subquery()
    if sort == "quality_desc":
        return [score.desc().nulls_last(), Job.id.desc()]
    return [score.asc().nulls_last(), Job.id.desc()]


def _current_score_subquery():
    return (
        select(JobQualityScore.overall_score)
        .where(
            JobQualityScore.job_id == Job.id,
            JobQualityScore.scoring_version
            == job_quality_service.SCORING_VERSION,
        )
        .order_by(JobQualityScore.calculated_at.desc())
        .limit(1)
        .scalar_subquery()
    )


def get_job(db: Session, job_id: int) -> Job | None:
    return db.get(Job, job_id)


def insert_jobs(
    db: Session,
    records: list[dict[str, Any]],
    *,
    source: str,
) -> InsertResult:
    """Insert normalized records without creating duplicates.

    Duplicate detection order:
      1. primary key  -> source + source_job_id
      2. secondary    -> canonical URL
      3. fallback     -> normalized company + title + location

    New records are DISCOVERED and get a seeded company + v1 quality score.
    Existing records are refreshed (UPDATED / REAPPEARED events as warranted)
    and their lifecycle timestamps advance.
    """
    inserted = 0
    duplicates = 0
    invalid: list[dict[str, Any]] = []

    for record in records:
        record["source"] = source
        ok, reason = _minimal_check(record)
        if not ok:
            invalid.append({"record": record, "reason": reason})
            continue

        existing = _find_duplicate(db, record)
        if existing is not None:
            _refresh_existing(db, existing, record)
            duplicates += 1
            continue

        now = datetime.now(timezone.utc)
        job = Job(**record)
        job.first_seen_at = now
        job.last_seen_at = now
        db.add(job)
        # autoflush is disabled on SessionLocal, so flush explicitly: it assigns
        # the id, makes the row visible to in-batch dedup + unique constraints.
        db.flush()

        job_events_service.record_event(
            db,
            job.id,
            job_events_service.DISCOVERED,
            event_data={"source": source},
            created_at=now,
        )
        company_service.upsert_company_for_job(db, job, seen_at=now)
        job_quality_service.calculate(db, job, as_of=now, store=True)
        inserted += 1

    db.commit()
    return InsertResult(
        inserted=inserted,
        duplicates=duplicates,
        invalid=invalid,
    )


def _refresh_existing(db: Session, job: Job, record: dict[str, Any]) -> None:
    """Merge a rediscovered record into an existing job."""
    now = datetime.now(timezone.utc)
    changes = job_events_service.find_changes(job, record)

    if changes:
        for field, diff in changes.items():
            setattr(job, field, diff["after"])
        job_events_service.record_event(
            db,
            job.id,
            job_events_service.UPDATED,
            event_data={
                "changes": changes,
                "source": record["source"],
            },
            created_at=now,
        )
        job_quality_service.calculate(db, job, as_of=now, store=True)
    elif job_events_service.is_reappeared(job, now):
        job_events_service.record_event(
            db,
            job.id,
            job_events_service.REAPPEARED,
            event_data={"source": record["source"]},
            created_at=now,
        )

    job.last_seen_at = now
    company_service.upsert_company_for_job(db, job, seen_at=now)
    db.flush()


def _minimal_check(record: dict[str, Any]) -> tuple[bool, str]:
    if not norm.clean_text(record.get("title")):
        return False, "missing title"
    if norm.clean_text(record.get("source_job_id")) or record.get("url"):
        return True, ""
    # No source ID and no URL: the dedup fallback (company+title+location)
    # can only anchor on a complete triple.
    if not (
        norm.clean_text(record.get("company"))
        and norm.clean_text(record.get("location"))
    ):
        return False, "missing source_job_id and url"
    return True, ""


def _find_duplicate(db: Session, record: dict[str, Any]) -> Job | None:
    source_job_id = norm.clean_text(record.get("source_job_id"))
    conditions = [Job.source == record["source"]]

    if source_job_id:
        conditions.append(Job.source_job_id == source_job_id)
    else:
        url = record.get("url")
        if url:
            conditions.append(Job.url == url)
        else:
            title = norm.clean_text(record.get("title"))
            company = norm.clean_text(record.get("company"))
            location = norm.clean_text(record.get("location"))
            if not title or not company:
                return None
            conditions.extend(
                [
                    func.lower(Job.title) == title.lower(),
                    func.lower(Job.company) == company.lower(),
                    func.lower(Job.location) == (location or "").lower(),
                ]
            )

    return db.scalar(select(Job).where(*conditions).limit(1))
