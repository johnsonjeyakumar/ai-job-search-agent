"""Skill gap analysis and learning plan API routes (Phase 11 + 11.1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services import learning_plan_service, skill_gap_service

router = APIRouter(prefix="/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SkillGapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    profile_id: int | None
    resume_id: int | None
    matched_skills: list[str]
    partial_skills: list[str]
    missing_skills: list[str]
    unknown_skills: list[str]
    evidence: list[dict]
    priorities: dict
    market_demand: dict
    readiness_label: str
    readiness_percentage: int
    readiness_breakdown: dict
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def _fmt_dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)


class LearningPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int | None
    profile_id: int
    target_role: str | None
    title: str
    status: str
    total_items: int
    completed_items: int
    verified_items: int
    estimated_effort_hours: int
    created_at: str
    updated_at: str

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _fmt_dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)


class LearningItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    skill: str
    priority: str
    objective: str
    estimated_hours: int
    prerequisites: list
    tasks: list
    completion_criteria: str | None
    evidence_requirement: str | None
    status: str
    evidence_links: list
    sort_order: int
    created_at: str
    updated_at: str

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _fmt_dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)


class UpdateItemStatusRequest(BaseModel):
    status: str


class AddEvidenceRequest(BaseModel):
    evidence_type: str
    url: str | None = None
    description: str | None = None


class AddResourceRequest(BaseModel):
    title: str
    resource_type: str
    url: str | None = None
    provider: str | None = None
    description: str | None = None
    free_or_paid: str = "UNKNOWN"
    difficulty: str = "UNKNOWN"
    source: str = "USER"


class ResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_id: int
    title: str
    resource_type: str
    url: str | None
    provider: str | None
    description: str | None
    free_or_paid: str
    difficulty: str
    source: str
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def _fmt_dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)


class SkillHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int
    skill: str
    previous_status: str | None
    new_status: str
    previous_confidence: str | None
    new_confidence: str | None
    source: str
    reason: str | None
    created_at: str

    @field_validator("created_at", mode="before")
    @classmethod
    def _fmt_dt(cls, v):
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)


class SkillAnalyticsResponse(BaseModel):
    matched_count: int
    partial_count: int
    missing_count: int
    unknown_count: int
    total_analyses: int
    total_learning_items: int
    completed_learning_items: int
    verified_learning_items: int
    in_progress_learning_items: int


# ---------------------------------------------------------------------------
# Skill Gap Analysis endpoints
# ---------------------------------------------------------------------------

@router.post("/gap-analysis/{job_id}", response_model=SkillGapResponse)
def create_gap_analysis(
    job_id: int,
    profile_id: int | None = Query(None),
    resume_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Compute skill gap analysis for a job."""
    try:
        analysis = skill_gap_service.analyze_skill_gaps(
            db, job_id, profile_id, resume_id
        )
        db.commit()
        return analysis
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/gap-analysis/{job_id}", response_model=SkillGapResponse | None)
def get_gap_analysis(
    job_id: int,
    db: Session = Depends(get_db),
):
    """Get the latest skill gap analysis for a job."""
    analysis = skill_gap_service.get_latest_analysis(db, job_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="No analysis found")
    return analysis


@router.get("/gap-analysis", response_model=list[SkillGapResponse])
def list_gap_analyses(
    profile_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List skill gap analyses."""
    return skill_gap_service.list_analyses(db, profile_id, limit)


# ---------------------------------------------------------------------------
# Learning Plan endpoints
# ---------------------------------------------------------------------------

@router.post("/learning-plans/{job_id}", response_model=LearningPlanResponse)
def create_learning_plan(
    job_id: int,
    profile_id: int | None = Query(None),
    resume_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Generate a learning plan from skill gap analysis."""
    try:
        plan = learning_plan_service.generate_learning_plan(
            db, job_id, profile_id, resume_id
        )
        db.commit()
        return plan
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/learning-plans", response_model=list[LearningPlanResponse])
def list_learning_plans(
    profile_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """List learning plans."""
    return learning_plan_service.list_plans(db, profile_id, limit)


@router.get("/learning-plans/{plan_id}", response_model=LearningPlanResponse)
def get_learning_plan(
    plan_id: int,
    db: Session = Depends(get_db),
):
    """Get a learning plan."""
    plan = learning_plan_service.get_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.get(
    "/learning-plans/{plan_id}/items",
    response_model=list[LearningItemResponse],
)
def list_learning_items(
    plan_id: int,
    db: Session = Depends(get_db),
):
    """List items in a learning plan."""
    return learning_plan_service.list_plan_items(db, plan_id)


@router.patch("/learning-items/{item_id}/status")
def update_item_status(
    item_id: int,
    body: UpdateItemStatusRequest,
    db: Session = Depends(get_db),
):
    """Update a learning item's status."""
    try:
        item = learning_plan_service.update_item_status(db, item_id, body.status)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        db.commit()
        return {"status": item.status, "id": item.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/learning-items/{item_id}/evidence")
def add_item_evidence(
    item_id: int,
    body: AddEvidenceRequest,
    db: Session = Depends(get_db),
):
    """Add evidence to a learning item."""
    try:
        evidence = learning_plan_service.add_item_evidence(
            db, item_id, body.evidence_type, body.url, body.description
        )
        db.commit()
        return {"id": evidence.id, "evidence_type": evidence.evidence_type}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Learning Resource endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/learning-items/{item_id}/resources",
    response_model=ResourceResponse,
)
def add_item_resource(
    item_id: int,
    body: AddResourceRequest,
    db: Session = Depends(get_db),
):
    """Add a learning resource to a learning item."""
    try:
        resource = learning_plan_service.add_item_resource(
            db, item_id, body.title, body.resource_type,
            body.url, body.provider, body.description,
            body.free_or_paid, body.difficulty, body.source,
        )
        db.commit()
        return resource
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/learning-items/{item_id}/resources",
    response_model=list[ResourceResponse],
)
def list_item_resources(
    item_id: int,
    db: Session = Depends(get_db),
):
    """List resources for a learning item."""
    return learning_plan_service.list_item_resources(db, item_id)


@router.delete("/learning-resources/{resource_id}")
def delete_resource(
    resource_id: int,
    db: Session = Depends(get_db),
):
    """Delete a learning resource."""
    deleted = learning_plan_service.delete_resource(db, resource_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Resource not found")
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Skill History endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=list[SkillHistoryResponse],
)
def list_skill_history(
    profile_id: int | None = Query(None),
    skill: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Get skill history, optionally filtered by skill."""
    if profile_id is None:
        return []
    return skill_gap_service.get_skill_history(db, profile_id, skill, limit)


@router.get(
    "/history/{skill}",
    response_model=list[SkillHistoryResponse],
)
def get_skill_history_by_name(
    skill: str,
    profile_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Get history for a specific skill."""
    if profile_id is None:
        return []
    return skill_gap_service.get_skill_history(db, profile_id, skill, limit)


# ---------------------------------------------------------------------------
# Analytics endpoint
# ---------------------------------------------------------------------------

@router.get("/analytics", response_model=SkillAnalyticsResponse)
def get_analytics(
    profile_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Get aggregate skill analytics."""
    return skill_gap_service.get_skill_analytics(db, profile_id)
