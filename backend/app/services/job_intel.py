"""Read-time enrichment: attach Phase 4 intelligence to Job objects.

The quality score is (re)computed against today's clock so the freshness
component reflects the current date, then persisted so API sorting and future
reads stay consistent with what the user sees.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.job import Job
from app.services import (
    company_service,
    freshness_service,
    job_events_service,
    job_quality_service,
    matches_service,
)


def enrich(
    db: Session,
    jobs: list[Job],
    *,
    companies: bool = False,
    events: bool = False,
) -> list[Job]:
    """Attach ``freshness``/``quality`` (and optionally ``company``/``events``)."""
    if not jobs:
        return jobs
    matches_service.ensure_decisions(db, jobs)
    for job in jobs:
        job.freshness = freshness_service.classify(job.posted_date)
        job.quality = job_quality_service.calculate(db, job, store=True)
        job.match = matches_service.match_view(db, job)
        job.opportunity = matches_service.opportunity_view(db, job)
        if companies:
            job.company_info = company_service.company_view_for_job(db, job)
        if events:
            job.recent_events = job_events_service.recent_events(
                db, job.id, limit=10
            )
    # Persist freshly evaluated scores (see module docstring).
    db.commit()
    return jobs
