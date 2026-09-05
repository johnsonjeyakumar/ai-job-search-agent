"""Job listing, filtering, pagination, and duplicate-safe insertion."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.job_sources import normalizer as norm
from app.models.job import Job


@dataclass
class InsertResult:
    inserted: int
    duplicates: int
    invalid: list[dict[str, Any]]


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

    query = select(Job)
    if conditions:
        query = query.where(*conditions)
    query = query.order_by(Job.discovered_date.desc(), Job.id.desc())

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(
        db.scalars(query.offset((page - 1) * limit).limit(limit))
    )
    return items, total


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

        if _find_duplicate(db, record) is not None:
            duplicates += 1
            continue

        db.add(Job(**record))
        inserted += 1

    db.commit()
    return InsertResult(
        inserted=inserted,
        duplicates=duplicates,
        invalid=invalid,
    )


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
