"""Mock interview session service (Phase 10).

Manages mock interview sessions: creation, answering, progress, finish,
evaluation. Sessions persist across multiple practice runs.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.interview import InterviewSession
from app.services import interview_prep_service as prep


class MockInterviewError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def create_session(
    db: Session,
    application_id: int,
    *,
    interview_id: int | None = None,
    question_count: int = 10,
    technical_pct: int = 60,
    behavioral_pct: int = 20,
    project_pct: int = 20,
    difficulty: str = "MEDIUM",
) -> InterviewSession:
    """Create and persist a new mock interview session with generated questions."""
    # Determine category mix from percentages.
    categories = []
    tech_n = max(1, int(question_count * technical_pct / 100))
    beh_n = max(0, int(question_count * behavioral_pct / 100))
    proj_n = question_count - tech_n - beh_n
    if tech_n > 0:
        categories.extend(["TECHNICAL"] * tech_n)
    if beh_n > 0:
        categories.extend(["BEHAVIORAL"] * beh_n)
    if proj_n > 0:
        categories.extend(["PROJECT"] * proj_n)
    # Pad if rounding left us short.
    while len(categories) < question_count:
        categories.append("TECHNICAL")

    # Generate questions from the application context.
    generated = prep.generate_questions(
        db,
        application_id,
        interview_id=interview_id,
        categories=categories,
        count=question_count,
    )

    questions_data = [
        {
            "question_id": None,
            "question": q.question,
            "category": q.category,
            "difficulty": q.difficulty,
            "source": q.source,
            "rationale": q.rationale,
            "source_context": q.source_context,
        }
        for q in generated
    ]

    config = {
        "question_count": question_count,
        "technical_pct": technical_pct,
        "behavioral_pct": behavioral_pct,
        "project_pct": project_pct,
        "difficulty": difficulty,
        "categories": categories,
    }

    session = InterviewSession(
        application_id=application_id,
        interview_id=interview_id,
        config=config,
        questions=questions_data,
        answers=[],
        feedback={},
        final_summary={},
    )
    db.add(session)
    db.flush()
    return session


def get_session(db: Session, session_id: int) -> InterviewSession:
    s = db.get(InterviewSession, session_id)
    if s is None:
        raise MockInterviewError(f"Mock session {session_id} not found.", 404)
    return s


def answer_question(
    db: Session,
    session_id: int,
    question_index: int,
    answer_text: str,
) -> InterviewSession:
    """Record an answer for a specific question in the session."""
    s = get_session(db, session_id)
    if s.completed_at is not None:
        raise MockInterviewError("Session is already completed.", 409)
    questions = s.questions or []
    if question_index < 0 or question_index >= len(questions):
        raise MockInterviewError(f"Invalid question index: {question_index}.", 422)

    answers = list(s.answers or [])
    # Ensure answers list is long enough.
    while len(answers) <= question_index:
        answers.append(None)
    answers[question_index] = {
        "question_index": question_index,
        "answer": answer_text,
        "answered_at": datetime.now().isoformat(),
    }
    s.answers = answers
    db.flush()
    return s


def finish_session(
    db: Session,
    session_id: int,
) -> InterviewSession:
    """Complete the session and generate a summary/evaluation."""
    s = get_session(db, session_id)
    if s.completed_at is not None:
        raise MockInterviewError("Session already completed.", 409)

    s.completed_at = datetime.now()
    questions = s.questions or []
    answers = s.answers or []

    # Evaluate each answer deterministically.
    evaluations = []
    for idx, q in enumerate(questions):
        ans = answers[idx] if idx < len(answers) else None
        answer_text = ans.get("answer", "") if ans else ""
        checks = prep.deterministic_answer_checks(answer_text, q.get("question", ""))
        evaluations.append({
            "question_index": idx,
            "category": q.get("category"),
            "answered": bool(answer_text.strip()),
            "checks": checks,
            "label": _evaluate_answer_label(checks),
        })

    # Overall summary.
    answered_count = sum(1 for e in evaluations if e["answered"])
    strong = sum(1 for e in evaluations if e["label"] == "STRONG")
    good = sum(1 for e in evaluations if e["label"] == "GOOD")
    needs_improvement = sum(1 for e in evaluations if e["label"] == "NEEDS_IMPROVEMENT")
    weak = sum(1 for e in evaluations if e["label"] == "WEAK")
    unanswered = len(evaluations) - answered_count

    # Category breakdown.
    categories_seen = {}
    for e in evaluations:
        cat = e.get("category", "UNKNOWN")
        if cat not in categories_seen:
            categories_seen[cat] = {"total": 0, "answered": 0, "strong": 0}
        categories_seen[cat]["total"] += 1
        if e["answered"]:
            categories_seen[cat]["answered"] += 1
        if e["label"] == "STRONG":
            categories_seen[cat]["strong"] += 1

    overall = "GOOD"
    if strong > good and strong > needs_improvement:
        overall = "STRONG"
    elif needs_improvement > strong and needs_improvement > good:
        overall = "NEEDS_IMPROVEMENT"
    elif unanswered > len(evaluations) * 0.5:
        overall = "WEAK"

    final_summary = {
        "overall_label": overall,
        "total_questions": len(evaluations),
        "answered": answered_count,
        "unanswered": unanswered,
        "strong": strong,
        "good": good,
        "needs_improvement": needs_improvement,
        "weak": weak,
        "category_breakdown": categories_seen,
        "evaluations": evaluations,
        "message": (
            f"You answered {answered_count}/{len(evaluations)} questions. "
            f"Strong: {strong}, Good: {good}, Needs improvement: {needs_improvement}, Weak: {weak}."
        ),
    }

    s.final_summary = final_summary
    s.feedback = final_summary
    db.flush()
    return s


def list_sessions(
    db: Session,
    application_id: int,
) -> list[InterviewSession]:
    return list(
        db.scalars(
            select(InterviewSession)
            .where(InterviewSession.application_id == application_id)
            .order_by(InterviewSession.created_at.desc())
        ).all()
    )


def _evaluate_answer_label(checks: dict) -> str:
    """Deterministic answer quality label."""
    if checks.get("empty"):
        return "WEAK"
    if checks.get("too_short"):
        return "WEAK"
    if checks.get("word_count", 0) < 30:
        return "NEEDS_IMPROVEMENT"
    if checks.get("word_count", 0) > 500:
        return "NEEDS_IMPROVEMENT"
    if checks.get("word_count", 0) >= 50:
        return "STRONG"
    return "GOOD"
