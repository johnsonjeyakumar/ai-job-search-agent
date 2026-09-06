"""Phase 5 orchestrator: persistence, staleness, and read views.

Derives the personal match and the opportunity decision for jobs, stores them
(``job_matches`` + ``opportunity_scores``), and only recomputes a row when its
context hash (matching version + profile + preferences + active resume) has
changed or when a stored row is missing. Freshness decay is picked up by
comparing the stored freshness score against the freshly evaluated one.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job import Job, JobMatch
from app.models.opportunity import OpportunityScore
from app.models.quality import JobQualityScore
from app.services import (
    job_quality_service,
    matching_service,
    opportunity_service,
)


def ensure_decisions(
    db: Session,
    jobs: list[Job],
    *,
    force: bool = False,
    commit: bool = True,
) -> int:
    """Ensure fresh match + opportunity rows exist for ``jobs``.

    Returns the number of match rows that were (re)computed. Opportunity rows
    are refreshed when the match was recomputed or when freshness decayed.
    """
    if not jobs:
        return 0
    context = matching_service.build_user_context(db)
    profile_id = context.profile.id if context.profile is not None else None
    recomputed = 0

    for job in jobs:
        match_row = _stored_match(db, job.id, profile_id)
        needs_match = force or match_row is None or match_row.context_key != context.context_key
        if not needs_match:
            # Opportunity may still need a freshness refresh; do a light check.
            opportunity_row = _stored_opportunity(db, job.id, profile_id)
            if opportunity_row is not None and not _opportunity_stale(db, job, opportunity_row):
                continue
            compute = opportunity_service.calculate(
                match_score=(
                    float(match_row.match_score)
                    if match_row.match_score is not None
                    else None
                ),
                quality=job_quality_service.calculate(db, job, store=True),
                freshness_raw=_freshness_raw(job),
                blockers=list(opportunity_row.blockers or []),
            )
            _store_opportunity(db, job, profile_id, compute)
            continue

        computation = matching_service.calculate(db, job)
        match_row = _store_match(db, job, profile_id, computation)

        quality = job_quality_service.calculate(db, job, store=True)
        compute = opportunity_service.calculate(
            match_score=(
                float(computation.match_score)
                if computation.match_score is not None
                else None
            ),
            quality=quality,
            freshness_raw=_freshness_raw(job),
            blockers=list(computation.blockers),
        )
        _store_opportunity(db, job, profile_id, compute)
        recomputed += 1

    if commit:
        db.commit()
    return recomputed


def _match_profile_clause(profile_id: int | None):
    if profile_id is None:
        return JobMatch.profile_id.is_(None)
    return JobMatch.profile_id == profile_id


def _stored_match(db: Session, job_id: int, profile_id: int | None) -> JobMatch | None:
    return db.scalar(
        select(JobMatch).where(
            JobMatch.job_id == job_id, _match_profile_clause(profile_id)
        )
    )


def _opportunity_profile_clause(profile_id: int | None):
    if profile_id is None:
        return OpportunityScore.profile_id.is_(None)
    return OpportunityScore.profile_id == profile_id


def _stored_opportunity(
    db: Session, job_id: int, profile_id: int | None
) -> OpportunityScore | None:
    return db.scalar(
        select(OpportunityScore).where(
            OpportunityScore.job_id == job_id,
            _opportunity_profile_clause(profile_id),
            OpportunityScore.opportunity_version == opportunity_service.OPPORTUNITY_VERSION,
        )
    )


def _opportunity_stale(db: Session, job: Job, row: OpportunityScore) -> bool:
    fresh = job_quality_service.calculate(db, job, store=True)
    if row.freshness_score != fresh.components.get("freshness", {}).get("score"):
        return True
    return row.quality_score != fresh.overall_score


def _freshness_raw(job: Job) -> str | None:
    from app.services import freshness_service

    return freshness_service.classify(job.posted_date).status


def _store_match(
    db: Session, job: Job, profile_id: int | None, computation: matching_service.MatchComputation
) -> JobMatch:
    row = _stored_match(db, job.id, profile_id)
    if row is None:
        row = JobMatch(job_id=job.id, profile_id=profile_id)
        db.add(row)
    row.match_score = computation.match_score
    row.recommendation = computation.recommendation
    row.confidence_score = computation.confidence_score
    row.matching_version = computation.matching_version
    row.context_key = computation.context_key
    row.criteria_breakdown = {
        key: {
            "score": comp.score,
            "status": comp.status,
            "message": comp.message,
        }
        for key, comp in computation.components.items()
    }
    row.matched_skills = computation.matched_skills
    row.missing_skills = computation.missing_skills
    row.matched_requirements = computation.matched_requirements
    row.partial_requirements = computation.partial_requirements
    row.missing_requirements = computation.missing_requirements
    row.unknown_requirements = computation.unknown_requirements
    row.evidence = computation.evidence
    row.explanation = computation.explanation
    row.calculated_at = computation.calculated_at
    db.flush()
    return row


def _store_opportunity(
    db: Session,
    job: Job,
    profile_id: int | None,
    computation: opportunity_service.OpportunityComputation,
) -> OpportunityScore:
    row = _stored_opportunity(db, job.id, profile_id)
    if row is None:
        row = OpportunityScore(job_id=job.id, profile_id=profile_id)
        db.add(row)
    row.match_score = computation.match_score
    row.quality_score = computation.quality_score
    row.freshness_score = computation.freshness_score
    row.company_score = computation.company_score
    row.opportunity_score = computation.opportunity_score
    row.recommendation = computation.recommendation
    row.opportunity_version = computation.opportunity_version
    row.explanation = computation.explanation
    row.blockers = computation.blockers
    row.calculated_at = computation.calculated_at
    db.flush()
    return row


# --------------------------------------------------------------------------
# Read views
# --------------------------------------------------------------------------


def match_view(db: Session, job: Job) -> JobMatch | None:
    context = matching_service.build_user_context(db)
    profile_id = context.profile.id if context.profile is not None else None
    return _stored_match(db, job.id, profile_id)


def opportunity_view(db: Session, job: Job) -> OpportunityScore | None:
    context = matching_service.build_user_context(db)
    profile_id = context.profile.id if context.profile is not None else None
    return _stored_opportunity(db, job.id, profile_id)


def stats_summary(db: Session) -> dict:
    """Aggregate Phase 5 numbers for the dashboard/stats endpoint."""
    context = matching_service.build_user_context(db)
    profile_id = context.profile.id if context.profile is not None else None
    query = select(OpportunityScore).where(
        OpportunityScore.opportunity_version == opportunity_service.OPPORTUNITY_VERSION,
        _opportunity_profile_clause(profile_id),
    )
    rows = list(db.scalars(query))

    match_scores = [float(r.match_score) for r in rows if r.match_score is not None]
    opp_scores = [float(r.opportunity_score) for r in rows]

    counts: dict[str, int] = {band: 0 for band in matching_service.RECOMMENDATION_ORDER}
    for row in rows:
        band = row.recommendation
        counts[band] = counts.get(band, 0) + 1

    avg_quality = db.scalar(
        select(func.avg(JobQualityScore.overall_score)).where(
            JobQualityScore.scoring_version == job_quality_service.SCORING_VERSION
        )
    )

    return {
        "average_match_score": (
            round(sum(match_scores) / len(match_scores)) if match_scores else None
        ),
        "average_opportunity_score": (
            round(sum(opp_scores) / len(opp_scores)) if opp_scores else None
        ),
        "average_quality_score": round(float(avg_quality)) if avg_quality is not None else None,
        "recommendation_counts": counts,
        "evaluated_jobs": len(rows),
    }


def recalculate_all(db: Session) -> int:
    """Recompute decisions for every stored job (backfill script + tests)."""
    jobs = list(db.scalars(select(Job).order_by(Job.id)))
    return ensure_decisions(db, jobs, force=True)
