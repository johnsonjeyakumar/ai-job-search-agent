from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import SessionLocal, get_db
from app.schemas.automation import AutomationRunRead
from app.schemas.job import (
    JobListResponse,
    JobRead,
    JobSearchRequest,
    JobSearchResponse,
    JobStatsResponse,
)
from app.schemas.match import MatchRead, OpportunityRead
from app.services import (
    automation_service,
    job_intel,
    job_service,
    jobs_stats_service,
    matches_service,
    search_service,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

FreshnessFilter = Literal[
    "VERY_FRESH", "FRESH", "RECENT", "AGING", "STALE", "UNKNOWN"
]
RecommendationFilter = Literal[
    "APPLY_NOW", "APPLY", "REVIEW", "LOW_PRIORITY", "SKIP"
]
SortOption = Literal[
    "discovered",
    "posted",
    "freshness_desc",
    "freshness_asc",
    "quality_desc",
    "quality_asc",
    "match_desc",
    "match_asc",
    "opportunity_desc",
    "opportunity_asc",
]


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    role: str | None = None,
    location: str | None = None,
    source: str | None = None,
    remote_type: str | None = None,
    posted_within_days: int | None = Query(default=None, ge=1),
    company: str | None = None,
    freshness: FreshnessFilter | None = None,
    min_match_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    min_opportunity_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    recommendation: RecommendationFilter | None = None,
    sort: SortOption = "discovered",
    db: Session = Depends(get_db),
) -> JobListResponse:
    items, total = job_service.list_jobs(
        db,
        page=page,
        limit=limit,
        role=role,
        location=location,
        source=source,
        remote_type=remote_type,
        posted_within_days=posted_within_days,
        company=company,
        freshness=freshness,
        min_match_score=min_match_score,
        min_opportunity_score=min_opportunity_score,
        recommendation=recommendation,
        sort=sort,
    )
    job_intel.enrich(db, items)
    pages = (total + limit - 1) // limit
    return JobListResponse(
        items=items, page=page, limit=limit, total=total, pages=pages
    )


@router.get("/stats", response_model=JobStatsResponse)
def job_stats(db: Session = Depends(get_db)) -> JobStatsResponse:
    return jobs_stats_service.compute_stats(db)


@router.get("/runs/{run_id}", response_model=AutomationRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)) -> AutomationRunRead:
    run = automation_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/search", response_model=JobSearchResponse, status_code=202)
def start_search(
    request: JobSearchRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobSearchResponse:
    details = {
        "request": request.model_dump(exclude_none=True),
        "preferences": _preference_summary(db),
    }
    run = automation_service.start_run(
        db, run_type="job_discovery", source="apify", details=details
    )
    run_id = run.id

    def _background() -> None:
        with SessionLocal() as session:
            search_service.run_discovery(
                session,
                run_id,
                source_name="apify",
                overrides=request.model_dump(exclude_none=True),
            )

    background.add_task(_background)
    return JobSearchResponse(status="started", run_id=run_id)


def _preference_summary(db: Session) -> dict:
    from app.services.search_service import _effective_preferences

    prefs = _effective_preferences(db, {})
    return {
        "locations": prefs.get("preferred_locations"),
        "roles": (prefs.get("target_roles") or [None])[0],
        "posted_within_days": prefs.get("posted_within_days"),
    }


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobRead:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job_intel.enrich(db, [job], companies=True, events=True)
    return job


@router.get("/{job_id}/match", response_model=MatchRead)
def get_job_match(job_id: int, db: Session = Depends(get_db)) -> MatchRead:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    matches_service.ensure_decisions(db, [job])
    match_row = matches_service.match_view(db, job)
    if match_row is None:
        raise HTTPException(status_code=404, detail="Match not computed")
    return MatchRead.model_validate(match_row)


@router.get("/{job_id}/opportunity", response_model=OpportunityRead)
def get_job_opportunity(
    job_id: int, db: Session = Depends(get_db)
) -> OpportunityRead:
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    matches_service.ensure_decisions(db, [job])
    opp_row = matches_service.opportunity_view(db, job)
    if opp_row is None:
        raise HTTPException(status_code=404, detail="Opportunity not computed")
    return OpportunityRead.model_validate(opp_row)
