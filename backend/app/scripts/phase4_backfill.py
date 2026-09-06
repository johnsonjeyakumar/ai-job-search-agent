"""One-shot Phase 4 backfill for jobs collected before Phase 4 existed.

What it does, per existing job:
  * upserts a :class:`Company` row (lifecycle anchored to ``discovered_date``)
  * seeds a DISCOVERED event dated to the job's discovery (idempotent)
  * computes and stores the v1 quality score (evaluated as of today)

Run from ``backend/``::

    python -m app.scripts.phase4_backfill
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.event import JobEvent
from app.models.job import Job
from app.services import (
    company_service,
    job_events_service,
    job_quality_service,
)

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = {
        "jobs": 0,
        "companies": 0,
        "events_seeded": 0,
        "scores": 0,
    }
    with SessionLocal() as db:
        jobs = list(db.scalars(select(Job).order_by(Job.id)))
        for job in jobs:
            stats["jobs"] += 1
            seen = job.discovered_date

            company = company_service.upsert_company_for_job(
                db, job, seen_at=seen
            )
            if company is not None:
                stats["companies"] += 1

            has_event = db.scalar(
                select(JobEvent.id)
                .where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == job_events_service.DISCOVERED,
                )
                .limit(1)
            )
            if has_event is None:
                job_events_service.record_event(
                    db,
                    job.id,
                    job_events_service.DISCOVERED,
                    event_data={"source": job.source},
                    created_at=seen,
                )
                stats["events_seeded"] += 1

            job_quality_service.calculate(db, job, store=True)
            stats["scores"] += 1

        db.commit()

    logger.info(
        "Phase 4 backfill complete: %s jobs, %s companies, "
        "%s DISCOVERED events seeded, %s v1 scores stored.",
        stats["jobs"],
        stats["companies"],
        stats["events_seeded"],
        stats["scores"],
    )


if __name__ == "__main__":
    main()
