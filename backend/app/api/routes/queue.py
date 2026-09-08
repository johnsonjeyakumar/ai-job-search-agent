"""Application queue and autopilot API routes.

Endpoints for:
- Queue listing, stats, preflight, resolve, skip, and state transitions
- Autopilot run lifecycle (start/pause/resume/stop/status)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_db
from app.models.application_queue import AutopilotRun
from app.schemas.queue import (
    AutopilotRunResponse,
    AutopilotStartRequest,
    AutopilotStatusResponse,
    EnqueueRequest,
    QueueItemResolveRequest,
    QueueItemResponse,
    QueueItemSkipRequest,
    QueueListResponse,
    QueueStatsResponse,
)
from app.services import autopilot_service, queue_service

router = APIRouter(prefix="/api/v1/queue", tags=["queue"])


# ---------------------------------------------------------------------------
# Queue endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=QueueListResponse)
def list_queue(
    state: str | None = Query(default=None),
    attention: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List queue items with optional filters."""
    db = next(get_db())
    items = queue_service.list_queue(
        db, state=state, attention=attention, limit=limit, offset=offset
    )
    total = queue_service.count_queue(db, state=state, attention=attention)
    state_counts = queue_service.count_queue_by_state(db)
    attention_counts = queue_service.count_attention_items(db)
    return QueueListResponse(
        items=[QueueItemResponse.model_validate(i) for i in items],
        total=total,
        state_counts=state_counts,
        attention_counts=attention_counts,
    )


@router.get("/stats", response_model=QueueStatsResponse)
def get_queue_stats():
    """Get overall queue statistics."""
    db = next(get_db())
    return QueueStatsResponse(**autopilot_service.queue_stats(db))


@router.post("/enqueue", response_model=QueueItemResponse)
def enqueue_item(request: EnqueueRequest):
    """Add an approved package to the processing queue."""
    db = next(get_db())
    try:
        item = queue_service.enqueue(
            db,
            application_id=request.application_id,
            package_id=request.package_id,
            job_id=request.job_id,
        )
        db.commit()
        return QueueItemResponse.model_validate(item)
    except queue_service.QueueItemExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{item_id}", response_model=QueueItemResponse)
def get_queue_item(item_id: int):
    """Get a single queue item."""
    db = next(get_db())
    item = queue_service.get_queue_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Queue item {item_id} not found.")
    return QueueItemResponse.model_validate(item)


@router.post("/{item_id}/preflight", response_model=QueueItemResponse)
def run_preflight(item_id: int):
    """Run preflight checks and classify attention for a queue item."""
    db = next(get_db())
    try:
        item = queue_service.run_preflight(db, item_id)
        db.commit()
        return QueueItemResponse.model_validate(item)
    except queue_service.QueueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{item_id}/resolve", response_model=QueueItemResponse)
def resolve_item(item_id: int, request: QueueItemResolveRequest):
    """Resolve a NEEDS_INPUT item with user-provided data."""
    db = next(get_db())
    try:
        item = queue_service.resolve_item(
            db, item_id, resolution_data=request.resolution_data
        )
        db.commit()
        return QueueItemResponse.model_validate(item)
    except queue_service.QueueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except queue_service.QueueConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{item_id}/skip", response_model=QueueItemResponse)
def skip_item(item_id: int, request: QueueItemSkipRequest):
    """Skip a queue item."""
    db = next(get_db())
    try:
        item = queue_service.skip_item(db, item_id, reason=request.reason)
        db.commit()
        return QueueItemResponse.model_validate(item)
    except queue_service.QueueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except queue_service.QueueConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{item_id}/transition", response_model=QueueItemResponse)
def transition_item(
    item_id: int,
    target_state: str = Query(...),
    reason: str | None = Query(default=None),
):
    """Transition a queue item to a new state."""
    db = next(get_db())
    try:
        item = queue_service.transition_queue_state(
            db, item_id, target_state, reason=reason
        )
        db.commit()
        return QueueItemResponse.model_validate(item)
    except queue_service.QueueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except queue_service.QueueConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ---------------------------------------------------------------------------
# Autopilot endpoints
# ---------------------------------------------------------------------------

@router.post("/autopilot/start", response_model=AutopilotRunResponse)
def start_autopilot(request: AutopilotStartRequest):
    """Start a new autopilot run."""
    db = next(get_db())
    try:
        run = autopilot_service.start_autopilot(
            db, target_count=request.target_count
        )
        db.commit()
        return AutopilotRunResponse.model_validate(run)
    except autopilot_service.AutopilotConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/autopilot/{run_id}/pause", response_model=AutopilotRunResponse)
def pause_autopilot(run_id: int):
    """Pause an active autopilot run."""
    db = next(get_db())
    try:
        run = autopilot_service.pause_autopilot(db, run_id)
        db.commit()
        return AutopilotRunResponse.model_validate(run)
    except autopilot_service.AutopilotNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except autopilot_service.AutopilotConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/autopilot/{run_id}/resume", response_model=AutopilotRunResponse)
def resume_autopilot(run_id: int):
    """Resume a paused autopilot run."""
    db = next(get_db())
    try:
        run = autopilot_service.resume_autopilot(db, run_id)
        db.commit()
        return AutopilotRunResponse.model_validate(run)
    except autopilot_service.AutopilotNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except autopilot_service.AutopilotConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/autopilot/{run_id}/stop", response_model=AutopilotRunResponse)
def stop_autopilot(run_id: int):
    """Stop an autopilot run."""
    db = next(get_db())
    try:
        run = autopilot_service.stop_autopilot(db, run_id)
        db.commit()
        return AutopilotRunResponse.model_validate(run)
    except autopilot_service.AutopilotNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/autopilot/status", response_model=AutopilotStatusResponse)
def autopilot_status():
    """Get autopilot status and queue statistics."""
    db = next(get_db())
    active_run = autopilot_service.get_autopilot_status(db)
    stats = autopilot_service.queue_stats(db)
    return AutopilotStatusResponse(
        active_run=(
            AutopilotRunResponse.model_validate(active_run)
            if active_run
            else None
        ),
        pending_items=stats.get("pending_count", 0),
        attention_counts=stats.get("attention_counts", {}),
        daily_submitted=stats.get("daily_submitted", 0),
        daily_target=stats.get("daily_target", 5),
        daily_maximum=stats.get("daily_maximum", 10),
    )


@router.post("/autopilot/{run_id}/process-next", response_model=QueueItemResponse | None)
def process_next(run_id: int):
    """Process the next queued item in an autopilot run."""
    db = next(get_db())
    try:
        run = db.get(AutopilotRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Autopilot run {run_id} not found.")
        if run.status not in ("RUNNING",):
            raise HTTPException(
                status_code=409,
                detail=f"Run {run_id} is in status {run.status}, expected RUNNING.",
            )
        item = autopilot_service.process_next_item(db, run)
        db.commit()
        if item is None:
            return None
        return QueueItemResponse.model_validate(item)
    except autopilot_service.AutopilotNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except autopilot_service.AutopilotConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
