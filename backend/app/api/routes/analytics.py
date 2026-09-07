"""Application analytics API (Phase 8): funnel, performance, trends.

All values are deterministic — computed from tracked history with explicit
documented formulas (see ``application_analytics_service``).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services import application_analytics_service as analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])

RANGE_OPTIONS = analytics.DATE_RANGE_OPTIONS


def _range(range_name: str) -> str:
    if range_name not in RANGE_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"range must be one of {RANGE_OPTIONS}",
        )
    return range_name


def _handle(e: Exception) -> HTTPException:
    if isinstance(e, ValueError):
        return HTTPException(status_code=422, detail=str(e))
    return HTTPException(status_code=500, detail=str(e))


@router.get("/applications")
def applications_summary(
    range_name: str = Query(default="all", alias="range"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _range(range_name)
    try:
        return {
            "status_counts": analytics.status_counts(
                db, range_name, start=start, end=end
            ),
            "response_times": analytics.response_times(db),
            "by_role": analytics.by_role(db),
            "by_location": analytics.by_location(db),
            "by_company": analytics.by_company(db),
            "by_source": analytics.by_source(db),
            "by_resume": analytics.by_resume(db),
        }
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/funnel")
def funnel(
    range_name: str = Query(default="all", alias="range"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _range(range_name)
    try:
        return analytics.funnel(db, range_name, start=start, end=end)
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/roles")
def roles(
    range_name: str = Query(default="all", alias="range"),
    db: Session = Depends(get_db),
) -> dict:
    _range(range_name)
    return {
        "items": analytics.by_role(db),
        "small_sample_threshold": analytics.SMALL_SAMPLE_THRESHOLD,
    }


@router.get("/locations")
def locations(db: Session = Depends(get_db)) -> dict:
    return {
        "items": analytics.by_location(db),
        "small_sample_threshold": analytics.SMALL_SAMPLE_THRESHOLD,
    }


@router.get("/companies")
def companies(db: Session = Depends(get_db)) -> dict:
    return {
        "items": analytics.by_company(db),
        "small_sample_threshold": analytics.SMALL_SAMPLE_THRESHOLD,
    }


@router.get("/sources")
def sources(db: Session = Depends(get_db)) -> dict:
    return {
        "items": analytics.by_source(db),
        "small_sample_threshold": analytics.SMALL_SAMPLE_THRESHOLD,
    }


@router.get("/resumes")
def resumes(db: Session = Depends(get_db)) -> dict:
    return {
        "items": analytics.by_resume(db),
        "small_sample_threshold": analytics.SMALL_SAMPLE_THRESHOLD,
    }


@router.get("/trends")
def trends(
    range_name: str = Query(default="all", alias="range"),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    _range(range_name)
    try:
        return {"items": analytics.over_time(db, range_name, start=start, end=end)}
    except Exception as exc:
        raise _handle(exc) from exc


@router.get("/response-times")
def response_times(db: Session = Depends(get_db)) -> dict:
    return analytics.response_times(db)


@router.get("/follow-ups")
def follow_ups(db: Session = Depends(get_db)) -> dict:
    return analytics.follow_up_summary(db)


__all__ = ["router"]
