"""Interview API routes (Phase 10).

Endpoints for interview CRUD, question generation, answer practice,
mock sessions, feedback, outcome, and prep plan.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.interview import (
    AnswerSaveRequest,
    InterviewCreateRequest,
    InterviewFeedbackRequest,
    InterviewOutcomeRequest,
    InterviewRescheduleRequest,
    InterviewStatusRequest,
    InterviewUpdateRequest,
    MockAnswerRequest,
    MockSessionCreateRequest,
    PrepItemUpdateRequest,
    QuestionGenerateRequest,
)
from app.services import interview_prep_service as prep
from app.services import interview_service as interview_svc
from app.services import mock_interview_service as mock_svc
from app.services.interview_service import InterviewError
from app.services.mock_interview_service import MockInterviewError

router = APIRouter(prefix="/interviews", tags=["interviews"])


def _handle(e: Exception) -> HTTPException:
    if isinstance(e, (InterviewError, MockInterviewError)):
        return HTTPException(status_code=e.status_code, detail=e.message)
    if isinstance(e, ValueError):
        return HTTPException(status_code=422, detail=str(e))
    return HTTPException(status_code=500, detail="Internal server error.")


# ---------------------------------------------------------------------------
# Interview CRUD
# ---------------------------------------------------------------------------

@router.post("/applications/{application_id}/interviews")
def create_interview(
    application_id: int,
    payload: InterviewCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = interview_svc.create_interview(
            db,
            application_id,
            scheduled_at=payload.scheduled_at,
            interview_type=payload.interview_type,
            round_number=payload.round_number,
            interviewer_name=payload.interviewer_name,
            interviewer_role=payload.interviewer_role,
            meeting_url=payload.meeting_url,
            location=payload.location,
            notes=payload.notes,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": "Interview created.",
        "interview_id": row.id,
        "status": row.status,
    }


@router.get("/applications/{application_id}/interviews")
def list_interviews(
    application_id: int,
    db: Session = Depends(get_db),
) -> dict:
    items = interview_svc.list_interviews_for_application(db, application_id)
    return {
        "items": [
            {
                "id": i.id,
                "round": i.round,
                "interview_type": i.interview_type,
                "status": i.status,
                "outcome": i.outcome,
                "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
                "interviewer_name": i.interviewer_name,
                "interviewer_role": i.interviewer_role,
                "meeting_url": i.meeting_url,
                "location": i.location,
                "notes": i.notes,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
        "summary": interview_svc.interview_summary(db, application_id),
    }


@router.get("/{interview_id}")
def get_interview(
    interview_id: int,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.get_interview(db, interview_id)
    except InterviewError as exc:
        raise _handle(exc) from exc
    return {
        "id": i.id,
        "application_id": i.application_id,
        "round": i.round,
        "interview_type": i.interview_type,
        "status": i.status,
        "outcome": i.outcome,
        "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "interviewer_name": i.interviewer_name,
        "interviewer_role": i.interviewer_role,
        "meeting_url": i.meeting_url,
        "location": i.location,
        "notes": i.notes,
        "feedback_json": i.feedback_json,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


@router.patch("/{interview_id}")
def update_interview(
    interview_id: int,
    payload: InterviewUpdateRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.update_interview(
            db,
            interview_id,
            scheduled_at=payload.scheduled_at,
            interview_type=payload.interview_type,
            interviewer_name=payload.interviewer_name,
            interviewer_role=payload.interviewer_role,
            meeting_url=payload.meeting_url,
            location=payload.location,
            notes=payload.notes,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": "Interview updated.",
        "interview_id": i.id,
        "notes": i.notes,
        "scheduled_at": str(i.scheduled_at) if i.scheduled_at else None,
        "interview_type": i.interview_type,
        "interviewer_name": i.interviewer_name,
        "interviewer_role": i.interviewer_role,
        "meeting_url": i.meeting_url,
        "location": i.location,
    }


@router.post("/{interview_id}/status")
def change_status(
    interview_id: int,
    payload: InterviewStatusRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.change_interview_status(
            db, interview_id, payload.status, notes=payload.notes
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": f"Interview status updated to {i.status}.", "interview_id": i.id}


@router.post("/{interview_id}/complete")
def complete_interview(
    interview_id: int,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.complete_interview(db, interview_id)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Interview completed.", "interview_id": i.id}


@router.post("/{interview_id}/cancel")
def cancel_interview(
    interview_id: int,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.cancel_interview(db, interview_id)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Interview cancelled.", "interview_id": i.id}


@router.post("/{interview_id}/reschedule")
def reschedule_interview(
    interview_id: int,
    payload: InterviewRescheduleRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.reschedule_interview(
            db, interview_id, payload.scheduled_at, notes=payload.notes
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Interview rescheduled.", "interview_id": i.id}


@router.post("/{interview_id}/outcome")
def set_outcome(
    interview_id: int,
    payload: InterviewOutcomeRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        i = interview_svc.set_interview_outcome(
            db, interview_id, payload.outcome, notes=payload.notes
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": f"Interview outcome set to {i.outcome}.", "interview_id": i.id}


@router.post("/{interview_id}/feedback")
def set_feedback(
    interview_id: int,
    payload: InterviewFeedbackRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        feedback = payload.model_dump(exclude_none=True)
        i = interview_svc.set_interview_feedback(db, interview_id, feedback)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Interview feedback saved.", "interview_id": i.id}


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

@router.post("/applications/{application_id}/questions/generate")
def generate_questions(
    application_id: int,
    payload: QuestionGenerateRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        questions = prep.generate_questions(
            db,
            application_id,
            categories=payload.categories,
            count=payload.count,
        )
        saved = prep.save_questions(db, questions)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": f"{len(saved)} questions generated.",
        "items": [
            {
                "id": q.id,
                "question": q.question,
                "category": q.category,
                "difficulty": q.difficulty,
                "priority": q.priority,
                "source": q.source,
                "rationale": q.rationale,
                "source_context": q.source_context,
            }
            for q in saved
        ],
    }


@router.get("/applications/{application_id}/questions")
def list_questions(
    application_id: int,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    items = prep.list_questions(db, application_id, category=category)
    return {
        "items": [
            {
                "id": q.id,
                "question": q.question,
                "category": q.category,
                "difficulty": q.difficulty,
                "priority": q.priority,
                "source": q.source,
                "rationale": q.rationale,
                "source_context": q.source_context,
                "draft_answer": q.draft_answer,
                "answer_feedback": q.answer_feedback,
            }
            for q in items
        ],
    }


@router.post("/questions/{question_id}/answer")
def save_answer(
    question_id: int,
    payload: AnswerSaveRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        q = prep.save_answer(db, question_id, payload.draft_answer)
        checks = prep.deterministic_answer_checks(payload.draft_answer, q.question)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": "Answer saved.",
        "question_id": q.id,
        "checks": checks,
    }


@router.post("/questions/{question_id}/feedback")
def save_question_feedback(
    question_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Run deterministic feedback on a saved answer."""
    try:
        q = prep.get_question(db, question_id)
        if not q.draft_answer:
            return {"message": "No answer to evaluate.", "feedback": {}}
        checks = prep.deterministic_answer_checks(q.draft_answer, q.question)
        feedback = {
            "checks": checks,
            "word_count": checks.get("word_count", 0),
            "label": "STRONG" if checks.get("word_count", 0) >= 50 else (
                "GOOD" if checks.get("word_count", 0) >= 20 else "NEEDS_IMPROVEMENT"
            ),
        }
        prep.save_answer_feedback(db, question_id, feedback)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {"message": "Feedback generated.", "feedback": feedback}


# ---------------------------------------------------------------------------
# Mock interview sessions
# ---------------------------------------------------------------------------

@router.post("/applications/{application_id}/mock-sessions")
def create_mock_session(
    application_id: int,
    payload: MockSessionCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        s = mock_svc.create_session(
            db,
            application_id,
            interview_id=payload.interview_id,
            question_count=payload.question_count,
            technical_pct=payload.technical_pct,
            behavioral_pct=payload.behavioral_pct,
            project_pct=payload.project_pct,
            difficulty=payload.difficulty,
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": "Mock session created.",
        "session_id": s.id,
        "questions": s.questions,
        "config": s.config,
    }


@router.get("/{session_id}/mock-session")
def get_mock_session(
    session_id: int,
    db: Session = Depends(get_db),
) -> dict:
    try:
        s = mock_svc.get_session(db, session_id)
    except MockInterviewError as exc:
        raise _handle(exc) from exc
    return {
        "id": s.id,
        "application_id": s.application_id,
        "interview_id": s.interview_id,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "config": s.config,
        "questions": s.questions,
        "answers": s.answers,
        "feedback": s.feedback,
        "final_summary": s.final_summary,
    }


@router.post("/{session_id}/mock-session/answer")
def mock_answer(
    session_id: int,
    payload: MockAnswerRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        s = mock_svc.answer_question(
            db, session_id, payload.question_index, payload.answer
        )
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": "Answer recorded.",
        "session_id": s.id,
        "progress": {
            "answered": len([a for a in (s.answers or []) if a]),
            "total": len(s.questions or []),
        },
    }


@router.post("/{session_id}/mock-session/finish")
def finish_mock_session(
    session_id: int,
    db: Session = Depends(get_db),
) -> dict:
    try:
        s = mock_svc.finish_session(db, session_id)
        db.commit()
    except Exception as exc:
        raise _handle(exc) from exc
    return {
        "message": "Mock session completed.",
        "session_id": s.id,
        "final_summary": s.final_summary,
    }


@router.get("/applications/{application_id}/mock-sessions")
def list_mock_sessions(
    application_id: int,
    db: Session = Depends(get_db),
) -> dict:
    items = mock_svc.list_sessions(db, application_id)
    return {
        "items": [
            {
                "id": s.id,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "config": s.config,
                "final_summary": s.final_summary,
            }
            for s in items
        ],
    }


# ---------------------------------------------------------------------------
# Prep plan
# ---------------------------------------------------------------------------

@router.get("/applications/{application_id}/prep-items")
def list_prep_items(
    application_id: int,
    db: Session = Depends(get_db),
) -> dict:
    from sqlalchemy import select as sa_select

    from app.models.interview import InterviewPrepItem

    items = list(
        db.scalars(
            sa_select(InterviewPrepItem)
            .where(InterviewPrepItem.application_id == application_id)
            .order_by(InterviewPrepItem.sort_order)
        ).all()
    )
    return {
        "items": [
            {
                "id": p.id,
                "interview_id": p.interview_id,
                "label": p.label,
                "category": p.category,
                "status": p.status,
            }
            for p in items
        ],
    }


@router.patch("/prep-items/{item_id}")
def update_prep_item(
    item_id: int,
    payload: PrepItemUpdateRequest,
    db: Session = Depends(get_db),
) -> dict:
    from app.models.interview import InterviewPrepItem

    item = db.get(InterviewPrepItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Prep item {item_id} not found")
    item.status = payload.status
    db.commit()
    return {"message": "Prep item updated.", "item_id": item.id, "status": item.status}
