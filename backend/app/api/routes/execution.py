"""Phase 12 API routes for advanced application automation.

Provides endpoints for:
- Field mapping and catalog
- Application memory management
- Execution checkpoints and recovery
- Human approval workflows
- Analytics and security
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.application_execution.analytics import (
    AnalyticsStore,
)
from app.application_execution.checkpoint import (
    CheckpointStore,
)
from app.application_execution.field_catalog import (
    ALL_FIELD_CONCEPTS,
    CONCEPT_BY_CANONICAL,
)
from app.application_execution.human_approval import (
    ApprovalStore,
)
from app.application_execution.memory import (
    MemoryStore,
)
from app.application_execution.question_handler import (
    handle_question,
)
from app.application_execution.security import (
    FIELD_CLASSIFICATION,
    SecurityController,
)
from app.application_execution.semantic_mapper import (
    map_fields_semantic,
)

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])

# In-memory stores (would be database-backed in production)
_memory_store = MemoryStore()
_checkpoint_store = CheckpointStore()
_approval_store = ApprovalStore()
_analytics_store = AnalyticsStore()
_security_controller = SecurityController()


# ---------------------------------------------------------------------------
# Field Catalog
# ---------------------------------------------------------------------------

class FieldConceptResponse(BaseModel):
    canonical: str
    category: str
    aliases: list[str]
    sensitivity: str
    input_types: list[str]
    validation: str | None = None
    description: str = ""


@router.get("/catalog", response_model=list[FieldConceptResponse])
async def get_field_catalog():
    """Get the complete field catalog."""
    return [
        FieldConceptResponse(
            canonical=c.canonical,
            category=c.category,
            aliases=c.aliases,
            sensitivity=c.sensitivity,
            input_types=list(c.input_types),
            validation=c.validation,
            description=c.description,
        )
        for c in ALL_FIELD_CONCEPTS
    ]


@router.get("/catalog/{canonical}")
async def get_field_concept(canonical: str):
    """Get a specific field concept."""
    concept = CONCEPT_BY_CANONICAL.get(canonical.upper())
    if not concept:
        raise HTTPException(status_code=404, detail=f"Field '{canonical}' not found.")
    return {
        "canonical": concept.canonical,
        "category": concept.category,
        "aliases": concept.aliases,
        "sensitivity": concept.sensitivity,
        "input_types": list(concept.input_types),
        "validation": concept.validation,
        "description": concept.description,
    }


# ---------------------------------------------------------------------------
# Semantic Mapping
# ---------------------------------------------------------------------------

class DetectedFieldRequest(BaseModel):
    label: str
    kind: str = "text"
    value: str | None = None
    required: bool = False


class MappingRequest(BaseModel):
    fields: list[DetectedFieldRequest]
    user_verified: dict[str, str] | None = None


@router.post("/map-fields")
async def map_fields(request: MappingRequest):
    """Map detected fields to canonical concepts using semantic mapping."""
    from app.application_execution.base import DetectedField

    detected = [
        DetectedField(
            label=f.label,
            kind=f.kind,
            value=f.value,
        )
        for f in request.fields
    ]

    result = map_fields_semantic(detected, request.user_verified)

    return {
        "mappings": [
            {
                "canonical": m.canonical,
                "raw_label": m.raw_label,
                "confidence": m.confidence,
                "source": m.source,
                "mapping_method": m.mapping_method,
                "sensitivity": m.sensitivity,
                "ambiguity": m.ambiguity,
            }
            for m in result.mappings
        ],
        "unmapped_count": len(result.unmapped),
        "warnings": result.warnings,
        "summary": {
            "total": len(result.mappings),
            "mapped": result.mapped_count,
            "high_confidence": result.high_confidence_count,
            "needs_review": result.needs_review_count,
        },
    }


# ---------------------------------------------------------------------------
# Application Memory
# ---------------------------------------------------------------------------

class AnswerRequest(BaseModel):
    question: str
    answer: str
    answer_type: str = "TEXT"
    evidence: list[str] | None = None
    tags: list[str] | None = None


class AnswerResponse(BaseModel):
    id: int | None = None
    normalized_question: str
    raw_question: str
    answer: str
    verification_status: str
    sensitivity: str
    question_category: str


@router.post("/memory/answers", response_model=AnswerResponse)
async def add_answer(request: AnswerRequest):
    """Add or update a verified answer in memory."""
    verified = _memory_store.add_answer(
        question=request.question,
        answer=request.answer,
        answer_type=request.answer_type,
        evidence=request.evidence,
        tags=request.tags,
    )
    return AnswerResponse(
        id=verified.id,
        normalized_question=verified.normalized_question,
        raw_question=verified.raw_question,
        answer=verified.answer,
        verification_status=verified.verification_status,
        sensitivity=verified.sensitivity,
        question_category=verified.question_category,
    )


@router.get("/memory/answers")
async def list_answers(
    category: str | None = None,
    sensitivity: str | None = None,
    verification: str | None = None,
):
    """List answers with optional filters."""
    answers = _memory_store.list_answers(category, sensitivity, verification)
    return [a.to_dict() for a in answers]


@router.post("/memory/answers/{question}/verify")
async def verify_answer(question: str):
    """Mark an answer as user-verified."""
    success = _memory_store.verify_answer(question)
    if not success:
        raise HTTPException(status_code=404, detail="Answer not found.")
    return {"status": "verified", "question": question}


@router.post("/memory/answers/{question}/revoke")
async def revoke_answer(question: str):
    """Revoke a verified answer."""
    success = _memory_store.revoke_answer(question)
    if not success:
        raise HTTPException(status_code=404, detail="Answer not found.")
    return {"status": "revoked", "question": question}


# ---------------------------------------------------------------------------
# Unknown Questions
# ---------------------------------------------------------------------------

class UnknownQuestionRequest(BaseModel):
    question: str
    page_url: str | None = None
    field_type: str = "text"
    options: list[str] | None = None
    context: str = ""


@router.post("/memory/unknown-questions")
async def add_unknown_question(request: UnknownQuestionRequest):
    """Record an unknown question for user resolution."""
    unknown = _memory_store.add_unknown_question(
        question=request.question,
        page_url=request.page_url,
        field_type=request.field_type,
        options=request.options,
        context=request.context,
    )
    return {
        "raw_question": unknown.raw_question,
        "field_type": unknown.field_type,
        "available_options": unknown.available_options,
        "suggested_answer": unknown.suggested_answer,
    }


class ResolveQuestionRequest(BaseModel):
    answer: str
    verified: bool = True


@router.post("/memory/unknown-questions/{question}/resolve")
async def resolve_unknown_question(question: str, request: ResolveQuestionRequest):
    """Resolve an unknown question with a user-provided answer."""
    verified = _memory_store.resolve_unknown(
        question=question,
        answer=request.answer,
        verified=request.verified,
    )
    return {
        "status": "resolved",
        "question": question,
        "answer": verified.answer,
        "verification_status": verified.verification_status,
    }


# ---------------------------------------------------------------------------
# Question Handling
# ---------------------------------------------------------------------------

class QuestionRequest(BaseModel):
    question: str
    available_options: list[str] | None = None
    job_context: dict | None = None
    profile_context: dict | None = None


@router.post("/handle-question")
async def handle_question_endpoint(request: QuestionRequest):
    """Handle an application question using memory and context."""
    result = handle_question(
        question=request.question,
        memory=_memory_store,
        available_options=request.available_options,
        job_context=request.job_context,
        profile_context=request.profile_context,
    )

    return {
        "classification": {
            "raw_question": result.classification.raw_question,
            "normalized": result.classification.normalized,
            "category": result.classification.category,
            "sensitivity": result.classification.sensitivity,
            "is_known_concept": result.classification.is_known_concept,
            "answer_type": result.classification.answer_type,
        },
        "answer": result.answer,
        "source": result.source,
        "needs_user_input": result.needs_user_input,
        "is_blocked": result.is_blocked,
        "warning": result.warning,
    }


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

@router.get("/checkpoints/{run_id}")
async def get_checkpoints(run_id: str):
    """Get all checkpoints for a run."""
    checkpoints = _checkpoint_store.get_all(run_id)
    return {
        "run_id": run_id,
        "checkpoints": [
            {
                "id": cp.id,
                "checkpoint_type": cp.checkpoint_type,
                "step_number": cp.step_number,
                "timestamp": cp.timestamp,
                "state_snapshot": cp.state_snapshot,
                "fields_filled": cp.fields_filled,
                "questions_answered": cp.questions_answered,
                "errors": cp.errors,
            }
            for cp in checkpoints
        ],
        "can_resume": _checkpoint_store.can_resume(run_id),
        "resume_point": _checkpoint_store.get_resume_point(run_id),
    }


# ---------------------------------------------------------------------------
# Human Approval
# ---------------------------------------------------------------------------

class ApprovalRequestModel(BaseModel):
    run_id: str
    action: str
    details: dict | None = None
    reason: str = ""


@router.post("/approval/request")
async def request_approval(request: ApprovalRequestModel):
    """Request human approval for an action."""
    approval = _approval_store.request_approval(
        run_id=request.run_id,
        action=request.action,
        details=request.details,
        reason=request.reason,
    )
    return {
        "request_id": f"{approval.run_id}:{approval.action}",
        "action": approval.action,
        "status": approval.status,
        "reason": approval.reason,
        "created_at": approval.created_at,
    }


class ApprovalResponseModel(BaseModel):
    notes: str | None = None


@router.post("/approval/{run_id}/{action}/grant")
async def grant_approval(run_id: str, action: str, request: ApprovalResponseModel):
    """Grant approval for a request."""
    approval = _approval_store.grant_approval(run_id, action, request.notes)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    return {
        "request_id": f"{approval.run_id}:{approval.action}",
        "status": approval.status,
        "responded_at": approval.responded_at,
    }


@router.post("/approval/{run_id}/{action}/deny")
async def deny_approval(run_id: str, action: str, request: ApprovalResponseModel):
    """Deny approval for a request."""
    approval = _approval_store.deny_approval(run_id, action, request.notes)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    return {
        "request_id": f"{approval.run_id}:{approval.action}",
        "status": approval.status,
        "responded_at": approval.responded_at,
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/overall")
async def get_overall_analytics():
    """Get overall analytics across all runs."""
    return _analytics_store.get_overall_stats()


@router.get("/analytics/field-mapping")
async def get_field_mapping_analytics():
    """Get field mapping accuracy by field type."""
    return _analytics_store.get_field_mapping_accuracy()


@router.get("/analytics/platforms")
async def get_platform_analytics():
    """Get performance by platform."""
    return _analytics_store.get_platform_performance()


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@router.get("/security/classification/{canonical}")
async def get_field_classification(canonical: str):
    """Get the security classification for a field."""
    classification = FIELD_CLASSIFICATION.get(canonical.upper(), "PUBLIC")
    return {
        "canonical": canonical.upper(),
        "classification": classification,
    }


@router.post("/security/check-auto-fill")
async def check_auto_fill_security(
    canonical: str,
    value: str,
    verification_status: str = "UNVERIFIED",
):
    """Check if a field can be auto-filled."""
    check = _security_controller.check_auto_fill(canonical, value, verification_status)
    return {
        "allowed": check.allowed,
        "reason": check.reason,
        "classification": check.classification,
    }
