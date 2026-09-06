"""Dashboard statistics for Phase 4 (aggregates over collected jobs only)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.quality import JobQualityScore
from app.services import company_service, freshness_service, job_quality_service

FRESHNESS_STATUSES = (
    "very_fresh",
    "fresh",
    "recent",
    "aging",
    "stale",
    "unknown",
)


def compute_stats(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(Job)) or 0

    freshness_counts = {status: 0 for status in FRESHNESS_STATUSES}
    posted_dates = db.execute(select(Job.posted_date)).all()
    for (posted,) in posted_dates:
        status = freshness_service.classify(posted).status.lower()
        freshness_counts[status] += 1

    avg = db.scalar(
        select(func.round(func.avg(JobQualityScore.overall_score))).where(
            JobQualityScore.scoring_version
            == job_quality_service.SCORING_VERSION
        )
    )

    return {
        "total": total,
        "freshness_counts": freshness_counts,
        "avg_quality": int(avg) if avg is not None else None,
        "top_companies": company_service.top_companies(db, limit=5),
        "computed_at": datetime.now(timezone.utc),
    }
