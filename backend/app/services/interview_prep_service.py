"""Interview preparation service — question generation (Phase 10).

Generates job-specific, resume-based, technical, behavioral, and HR
questions. Deterministic prioritization; AI provides rationale only.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_package import ApplicationPackage
from app.models.interview import (
    QUESTION_CATEGORIES,
    InterviewQuestion,
)
from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume


def _application_with_context(db: Session, application_id: int) -> dict[str, Any] | None:
    """Load application + job + resume + profile + package context."""
    app = db.get(Application, application_id)
    if app is None:
        return None
    job = db.get(Job, app.job_id) if app.job_id else None
    resume = db.get(Resume, app.resume_id) if app.resume_id else None
    profile = db.get(Profile, app.profile_id) if app.profile_id else None
    package = db.scalar(
        select(ApplicationPackage)
        .where(ApplicationPackage.job_id == app.job_id)
        .order_by(ApplicationPackage.version.desc(), ApplicationPackage.id.desc())
        .limit(1)
    ) if app.job_id else None
    return {
        "application": app,
        "job": job,
        "resume": resume,
        "profile": profile,
        "package": package,
    }


def _make_question(
    *,
    application_id: int,
    interview_id: int | None,
    question: str,
    category: str,
    source: str,
    source_context: str,
    difficulty: str = "MEDIUM",
) -> InterviewQuestion:
    """Create an InterviewQuestion row (not yet added to session)."""
    return InterviewQuestion(
        application_id=application_id,
        interview_id=interview_id,
        question=question,
        category=category.upper(),
        difficulty=difficulty.upper(),
        source=source,
        source_context=source_context,
    )


def _deterministic_priority(source: str, category: str) -> str:
    """Determine priority from source and category (no LLM needed)."""
    if source == "JOB_REQUIREMENT" and category == "TECHNICAL":
        return "HIGH"
    if source == "RESUME_EVIDENCE" and category in ("PROJECT", "RESUME_BASED"):
        return "HIGH"
    if source == "JOB_REQUIREMENT" and category == "ROLE_SPECIFIC":
        return "HIGH"
    if source == "ROLE_PATTERN":
        return "MEDIUM"
    return "LOW"


def generate_questions(
    db: Session,
    application_id: int,
    *,
    interview_id: int | None = None,
    categories: list[str] | None = None,
    count: int = 10,
) -> list[InterviewQuestion]:
    """Generate interview questions from job/resume/profile context.

    Uses deterministic extraction from stored data; AI provides rationale
    when available. Returns generated InterviewQuestion rows (not yet
    committed — caller must commit).
    """
    ctx = _application_with_context(db, application_id)
    if ctx is None:
        return []

    job = ctx["job"]
    resume = ctx["resume"]
    profile = ctx["profile"]
    questions: list[InterviewQuestion] = []

    # Extract from job requirements (TECHNICAL + ROLE_SPECIFIC).
    if job is not None:
        reqs = job.requirements or []
        skills = job.skills or []
        for req in reqs[:5]:
            q = _make_question(
                application_id=application_id,
                interview_id=interview_id,
                question=f"Can you explain your experience with {req}?",
                category="TECHNICAL",
                source="JOB_REQUIREMENT",
                source_context=f"Job requirement: {req}",
                difficulty="MEDIUM",
            )
            questions.append(q)
        for skill in skills[:3]:
            q = _make_question(
                application_id=application_id,
                interview_id=interview_id,
                question=f"How have you used {skill} in previous projects?",
                category="TECHNICAL",
                source="JOB_REQUIREMENT",
                source_context=f"Required skill: {skill}",
                difficulty="MEDIUM",
            )
            questions.append(q)
        # Role-specific from job description.
        if job.description:
            desc_lower = job.description.lower()
            if "team" in desc_lower:
                questions.append(_make_question(
                    application_id=application_id,
                    interview_id=interview_id,
                    question="Describe your experience working in a team environment.",
                    category="BEHAVIORAL",
                    source="ROLE_PATTERN",
                    source_context="Job description mentions team collaboration",
                    difficulty="EASY",
                ))
            if "leadership" in desc_lower or "lead" in desc_lower:
                questions.append(_make_question(
                    application_id=application_id,
                    interview_id=interview_id,
                    question="Tell me about a time you led a project or initiative.",
                    category="BEHAVIORAL",
                    source="ROLE_PATTERN",
                    source_context="Job description mentions leadership",
                    difficulty="MEDIUM",
                ))
            if "fast-paced" in desc_lower or "agile" in desc_lower:
                questions.append(_make_question(
                    application_id=application_id,
                    interview_id=interview_id,
                    question="How do you handle working in a fast-paced environment?",
                    category="BEHAVIORAL",
                    source="ROLE_PATTERN",
                    source_context="Job description mentions fast-paced/agile",
                    difficulty="EASY",
                ))

    # Extract from resume (RESUME_BASED + PROJECT).
    if resume is not None and profile is not None:
        projects = profile.projects or []
        for proj in projects[:3]:
            proj_name = proj if isinstance(proj, str) else str(proj)
            questions.append(_make_question(
                application_id=application_id,
                interview_id=interview_id,
                question=(
                    f"Tell me about the project: {proj_name}. "
                    "What was your role and what did you build?"
                ),
                category="PROJECT",
                source="RESUME_EVIDENCE",
                source_context=f"Resume project: {proj_name}",
                difficulty="MEDIUM",
            ))
        skills = profile.skills or []
        for skill in skills[:3]:
            questions.append(_make_question(
                application_id=application_id,
                interview_id=interview_id,
                question=f"Why did you choose {skill} for your projects?",
                category="RESUME_BASED",
                source="RESUME_EVIDENCE",
                source_context=f"Resume skill: {skill}",
                difficulty="EASY",
            ))

    # Behavioral / HR standard questions.
    behavioral_qs = [
        "Tell me about yourself.",
        "Why are you interested in this role?",
        "Where do you see yourself in 5 years?",
        "What is your greatest strength?",
        "What is your biggest weakness?",
        "Describe a time you faced a challenge and how you overcame it.",
        "Tell me about a time you disagreed with a teammate. How did you resolve it?",
        "Why should we hire you?",
    ]
    for bq in behavioral_qs:
        cat = "HR" if bq in (
            "Tell me about yourself.",
            "Why are you interested in this role?",
            "Where do you see yourself in 5 years?",
            "What is your greatest strength?",
            "What is your biggest weakness?",
            "Why should we hire you?",
        ) else "BEHAVIORAL"
        questions.append(_make_question(
            application_id=application_id,
            interview_id=interview_id,
            question=bq,
            category=cat,
            source="ROLE_PATTERN",
            source_context="Standard interview question",
            difficulty="EASY",
        ))

    # Filter by requested categories.
    if categories:
        valid_cats = [c.upper() for c in categories if c.upper() in QUESTION_CATEGORIES]
        if valid_cats:
            questions = [q for q in questions if q.category in valid_cats]

    # Assign deterministic priorities.
    for q in questions:
        q.priority = _deterministic_priority(q.source, q.category)

    # Limit to requested count.
    return questions[:count]


def save_questions(
    db: Session,
    questions: list[InterviewQuestion],
) -> list[InterviewQuestion]:
    """Persist generated questions to the database."""
    for q in questions:
        db.add(q)
    db.flush()
    return questions


def list_questions(
    db: Session,
    application_id: int,
    *,
    interview_id: int | None = None,
    category: str | None = None,
) -> list[InterviewQuestion]:
    stmt = select(InterviewQuestion).where(
        InterviewQuestion.application_id == application_id
    )
    if interview_id is not None:
        stmt = stmt.where(InterviewQuestion.interview_id == interview_id)
    if category is not None:
        stmt = stmt.where(InterviewQuestion.category == category.upper())
    stmt = stmt.order_by(InterviewQuestion.priority, InterviewQuestion.created_at)
    return list(db.scalars(stmt).all())


def get_question(db: Session, question_id: int) -> InterviewQuestion:
    q = db.get(InterviewQuestion, question_id)
    if q is None:
        from app.services.interview_service import InterviewError
        raise InterviewError(f"Question {question_id} not found.", 404)
    return q


def save_answer(
    db: Session,
    question_id: int,
    draft_answer: str,
) -> InterviewQuestion:
    """Save a draft answer for a question."""
    q = get_question(db, question_id)
    q.draft_answer = draft_answer
    db.flush()
    return q


def save_answer_feedback(
    db: Session,
    question_id: int,
    feedback: dict,
) -> InterviewQuestion:
    """Save AI feedback on an answer."""
    q = get_question(db, question_id)
    q.answer_feedback = feedback
    db.flush()
    return q


def deterministic_answer_checks(draft_answer: str, question: str) -> dict:
    """Run deterministic checks on an answer (no LLM needed)."""
    checks = {
        "empty": len(draft_answer.strip()) == 0,
        "too_short": len(draft_answer.strip()) < 20,
        "too_long": len(draft_answer.strip()) > 2000,
        "contains_questionmarks": "?" in draft_answer,
        "word_count": len(draft_answer.split()),
    }
    return checks
