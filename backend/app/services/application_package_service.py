"""Application package orchestrator (Phase 6).

Puts the whole preparation pipeline together: duplicate protection, resume
selection, gap analysis + evidence mapping, tailoring suggestions, answers,
optional cover letter, truth/consistency validation, and the quality gate.
A package is a preparation artifact and stops at APPROVED; nothing here ever
submits an application. Regenerating always creates a new version and leaves
prior versions untouched.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_package import (
    ApplicationAnswer,
    ApplicationEvidence,
    ApplicationPackage,
    ApplicationTailoringSuggestion,
    ApplicationValidationFinding,
)
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import (
    application_answers_service as answers_service,
)
from app.services import (
    application_evidence_service as evidence_service,
)
from app.services import (
    application_quality_service as quality_service,
)
from app.services import (
    application_validation_service as validation_service,
)
from app.services import (
    cover_letter_service,
    job_service,
    matches_service,
    matching_service,
    tailoring_service,
)
from app.services import (
    requirement_extractor as rex,
)
from app.services import (
    resume_selection_service as selection_service,
)

STATUS_DRAFT = "DRAFT"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_READY_FOR_REVIEW = "READY_FOR_REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_ARCHIVED = "ARCHIVED"

_ACTIVE_STATUSES = (
    STATUS_DRAFT,
    STATUS_NEEDS_REVIEW,
    STATUS_READY_FOR_REVIEW,
    STATUS_APPROVED,
)


class PackageNotFoundError(Exception):
    pass


class PackageNotApprovableError(Exception):
    pass


class DuplicatePackageError(Exception):
    pass


# --------------------------------------------------------------------------
# Prepare pipeline
# --------------------------------------------------------------------------


async def prepare_package(
    db: Session,
    job_id: int,
    *,
    include_cover_letter: bool = False,
    force: bool = False,
) -> ApplicationPackage:
    """Prepare an application package for a real job (no submission)."""
    job = job_service.get_job(db, job_id)
    if job is None:
        raise PackageNotFoundError(f"Job {job_id} not found")

    existing = _existing_package(db, job_id)
    if existing is not None and not force:
        raise DuplicatePackageError(
            f"Possible previous application detected for job {job_id} "
            f"(package {existing.id}, status {existing.status}). "
            "It was not overwritten. Archive it or pass force to prepare anyway."
        )

    profile = db.scalar(select(Profile).order_by(Profile.id).limit(1))
    resumes = list(db.scalars(select(Resume).order_by(Resume.created_at.desc())))

    # Reuse Phase 5 decisions (no score changes, idempotent).
    matches_service.ensure_decisions(db, [job])
    context = matching_service.build_user_context(db)
    profile_id = context.profile.id if context.profile is not None else None
    match_row = matches_service.match_view(db, job)
    opp_row = matches_service.opportunity_view(db, job)

    bundle = rex.extract_job_requirements(job)
    computation = matching_service.calculate(db, job, bundle=bundle)

    selection = selection_service.select_resume(db, job, resumes, profile)
    selected_resume = None
    if selection.selected_id is not None:
        selected_resume = next((r for r in resumes if r.id == selection.selected_id), None)

    evidence_entries = evidence_service.build_evidence_entries(
        bundle=bundle,
        buckets={
            "matched_requirements": computation.matched_requirements,
            "partial_requirements": computation.partial_requirements,
            "missing_requirements": computation.missing_requirements,
            "unknown_requirements": computation.unknown_requirements,
        },
        profile=profile,
        preferences=context.preferences,
        resume=selected_resume,
        selection=selection,
    )

    suggestions = await tailoring_service.generate_tailoring_suggestions(
        db, job, profile, selected_resume, evidence_entries
    )

    target_role = selected_resume.target_role if selected_resume is not None else None
    answers = answers_service.draft_answers(
        db, job, profile, context.preferences, selected_resume, target_role
    )
    answers = await answers_service.refine_answers_with_ai(
        job, profile, selected_resume, answers
    )

    cover = await cover_letter_service.generate_cover_letter_for_package(
        db,
        job,
        profile,
        selected_resume,
        evidence_entries,
        requested=include_cover_letter,
    )

    findings = validation_service.validate_package_content(
        job=job,
        profile=profile,
        preferences=context.preferences,
        resume=selected_resume,
        answers=[a.to_dict() for a in answers],
        cover_letter=(
            {"text": cover.text, "status": cover.status}
            if cover.text is not None or cover.status == "needs_review"
            else None
        ),
        tailoring_suggestions=[
            {
                "requirement": s.requirement,
                "review_status": s.review_status,
            }
            for s in suggestions
        ],
    )
    findings.extend(
        await _ai_findings(db, job, profile, selected_resume)
    )

    quality = quality_service.evaluate(
        answers=[a.to_dict() for a in answers],
        findings=findings,
        selected_resume_id=selection.selected_id,
        cover_letter_status=cover.status,
        match_score=_float_or_none(getattr(match_row, "match_score", None)),
    )

    version = _next_version(db, job_id)
    package = ApplicationPackage(
        job_id=job_id,
        profile_id=profile_id,
        selected_resume_id=selection.selected_id,
        version=version,
        status=STATUS_READY_FOR_REVIEW if quality.gate == "PASS" else STATUS_NEEDS_REVIEW,
        readiness=quality.readiness,
        readiness_reasons=quality.readiness_reasons,
        quality_gate=quality.gate,
        quality_gate_summary=quality.summary,
        match_score=_float_or_none(getattr(match_row, "match_score", None)),
        opportunity_score=(
            _float_or_none(getattr(opp_row, "opportunity_score", None))
            if opp_row
            else None
        ),
        recommendation=getattr(opp_row, "recommendation", None) or "",
        resume_selection={
            "selected_resume_id": selection.selected_id,
            "score": selection.score,
            "explanation": selection.explanation,
            "candidates": [
                {
                    "resume_id": c.resume_id,
                    "name": c.name,
                    "target_role": c.target_role,
                    "score": c.score,
                    "reasons": c.reasons,
                }
                for c in selection.candidates
            ],
        },
        gap_analysis=[
            {
                "requirement": e.requirement,
                "category": e.category,
                "status": e.status,
                "evidence": e.evidence,
                "source": e.source,
                "confidence": e.confidence,
                "reason": e.reason,
            }
            for e in evidence_entries
        ],
        cover_letter=cover.text,
        cover_letter_status=cover.status,
        duplicate_disclaimer=_duplicate_disclaimer(db, job),
    )
    db.add(package)
    db.flush()

    for entry in evidence_entries:
        db.add(
            ApplicationEvidence(
                package_id=package.id,
                requirement=entry.requirement,
                category=entry.category,
                status=entry.status,
                evidence=entry.evidence,
                source=entry.source,
                confidence=entry.confidence,
            )
        )
    for suggestion in suggestions:
        db.add(
            ApplicationTailoringSuggestion(
                package_id=package.id,
                resume_id=suggestion.resume_id,
                requirement=suggestion.requirement,
                category=suggestion.category,
                existing_evidence=suggestion.existing_evidence,
                suggested_wording=suggestion.suggested_wording,
                reason=suggestion.reason,
                confidence=suggestion.confidence,
                review_status=suggestion.review_status,
            )
        )
    for answer in answers:
        db.add(
            ApplicationAnswer(
                package_id=package.id,
                category=answer.category,
                question=answer.question,
                answer=answer.answer,
                source_evidence=answer.source_evidence,
                confidence=answer.confidence,
                validation_status=answer.validation_status,
                feedback=answer.feedback,
            )
        )
    for finding in findings:
        db.add(
            ApplicationValidationFinding(
                package_id=package.id,
                section=finding.section,
                check=finding.check,
                status=finding.status,
                message=finding.message,
            )
        )

    db.commit()
    db.refresh(package)
    return package


async def _ai_findings(db, job, profile, resume) -> list:
    from pydantic import ValidationError

    from app.ai.registry import get_provider
    from app.schemas.ai_application import AIValidationFinding

    provider = get_provider()
    if provider.name == "mock":
        return []
    payload = await provider.validate_application(job, profile, resume, {})
    if not payload:
        return []
    findings: list[validation_service.ValidationFinding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            parsed = AIValidationFinding.model_validate(item)
        except (ValidationError, TypeError, ValueError):
            continue
        status = (
            validation_service.INVALID
            if parsed.status == "INVALID"
            else validation_service.NEEDS_REVIEW
            if parsed.status == "NEEDS_REVIEW"
            else validation_service.PASS
        )
        findings.append(
            validation_service.ValidationFinding(
                section="package", check=parsed.check, status=status, message=parsed.message
            )
        )
    return findings


def _existing_package(db: Session, job_id: int) -> ApplicationPackage | None:
    return db.scalar(
        select(ApplicationPackage)
        .where(ApplicationPackage.job_id == job_id)
        .where(ApplicationPackage.status.in_(_ACTIVE_STATUSES))
        .order_by(ApplicationPackage.version.desc())
        .limit(1)
    )


def _next_version(db: Session, job_id: int) -> int:
    current = db.scalar(
        select(func.max(ApplicationPackage.version)).where(
            ApplicationPackage.job_id == job_id
        )
    )
    return (current or 0) + 1


def _duplicate_disclaimer(db: Session, job) -> str | None:
    previous = db.scalar(
        select(Application)
        .where(Application.job_id == job.id)
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if previous is not None:
        return (
            f"A submission for this job is already tracked (application "
            f"#{previous.id}, status '{previous.status}'). Preparing a package "
            "is not a submission."
        )
    prior = db.scalar(
        select(func.count(ApplicationPackage.id)).where(
            ApplicationPackage.job_id == job.id,
            ApplicationPackage.status.in_(_ACTIVE_STATUSES),
        )
    )
    if prior:
        return "A prior package already exists for this job; it was preserved."
    return None


# --------------------------------------------------------------------------
# Read / manage
# --------------------------------------------------------------------------


def get_package(db: Session, package_id: int) -> ApplicationPackage | None:
    return db.get(ApplicationPackage, package_id)


def list_packages(
    db: Session, status: str | None = None, include_history: bool = False
) -> list[ApplicationPackage]:
    query = select(ApplicationPackage).order_by(ApplicationPackage.created_at.desc())
    if status:
        query = query.where(ApplicationPackage.status == status)
    if not include_history:
        latest = select(func.max(ApplicationPackage.id)).group_by(ApplicationPackage.job_id)
        query = query.where(ApplicationPackage.id.in_(latest))
    return list(db.scalars(query))


def get_answers(db: Session, package_id: int) -> list[ApplicationAnswer]:
    return list(
        db.scalars(
            select(ApplicationAnswer)
            .where(ApplicationAnswer.package_id == package_id)
            .order_by(ApplicationAnswer.id)
        )
    )


def get_evidence(db: Session, package_id: int) -> list[ApplicationEvidence]:
    return list(
        db.scalars(
            select(ApplicationEvidence)
            .where(ApplicationEvidence.package_id == package_id)
            .order_by(ApplicationEvidence.id)
        )
    )


def get_suggestions(db: Session, package_id: int) -> list[ApplicationTailoringSuggestion]:
    return list(
        db.scalars(
            select(ApplicationTailoringSuggestion)
            .where(ApplicationTailoringSuggestion.package_id == package_id)
            .order_by(ApplicationTailoringSuggestion.id)
        )
    )


def get_findings(db: Session, package_id: int) -> list[ApplicationValidationFinding]:
    return list(
        db.scalars(
            select(ApplicationValidationFinding)
            .where(ApplicationValidationFinding.package_id == package_id)
            .order_by(ApplicationValidationFinding.id)
        )
    )


def preview_package(db: Session, package_id: int) -> dict:
    """Full read model for the application preview page."""
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    job = job_service.get_job(db, package.job_id)
    resume = db.get(Resume, package.selected_resume_id) if package.selected_resume_id else None
    answers = get_answers(db, package_id)
    evidence_entries = get_evidence(db, package_id)
    suggestions = get_suggestions(db, package_id)
    findings = get_findings(db, package_id)

    return {
        "id": package.id,
        "version": package.version,
        "status": package.status,
        "readiness": package.readiness,
        "readiness_reasons": package.readiness_reasons,
        "quality_gate": package.quality_gate,
        "quality_gate_summary": package.quality_gate_summary,
        "match_score": package.match_score,
        "opportunity_score": package.opportunity_score,
        "recommendation": package.recommendation,
        "cover_letter": package.cover_letter,
        "cover_letter_status": package.cover_letter_status,
        "duplicate_disclaimer": package.duplicate_disclaimer,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
        "job": _job_summary(job),
        "resume": _resume_summary(resume),
        "resume_selection": package.resume_selection or {},
        "gap_analysis": package.gap_analysis or [],
        "evidence": [
            {
                "id": e.id,
                "requirement": e.requirement,
                "category": e.category,
                "status": e.status,
                "evidence": e.evidence,
                "source": e.source,
                "confidence": e.confidence,
            }
            for e in evidence_entries
        ],
        "tailoring_suggestions": [
            {
                "id": s.id,
                "requirement": s.requirement,
                "category": s.category,
                "existing_evidence": s.existing_evidence,
                "suggested_wording": s.suggested_wording,
                "reason": s.reason,
                "confidence": s.confidence,
                "review_status": s.review_status,
                "applied": s.applied,
            }
            for s in suggestions
        ],
        "answers": [
            {
                "id": a.id,
                "category": a.category,
                "question": a.question,
                "answer": a.answer,
                "source_evidence": a.source_evidence,
                "confidence": a.confidence,
                "validation_status": a.validation_status,
                "feedback": a.feedback,
            }
            for a in answers
        ],
        "validation_findings": [
            {
                "id": f.id,
                "section": f.section,
                "check": f.check,
                "status": f.status,
                "message": f.message,
            }
            for f in findings
        ],
    }


def summary_row(db: Session, package: ApplicationPackage) -> dict:
    job = job_service.get_job(db, package.job_id)
    resume = db.get(Resume, package.selected_resume_id) if package.selected_resume_id else None
    return {
        "id": package.id,
        "job_id": package.job_id,
        "job_title": job.title if job else None,
        "company": job.company if job else None,
        "resume_name": resume.name if resume else None,
        "version": package.version,
        "status": package.status,
        "readiness": package.readiness,
        "quality_gate": package.quality_gate,
        "match_score": package.match_score,
        "opportunity_score": package.opportunity_score,
        "recommendation": package.recommendation,
        "created_at": package.created_at,
        "updated_at": package.updated_at,
    }


def _job_summary(job) -> dict:
    if job is None:
        return {}
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote_type": job.remote_type,
        "employment_type": job.employment_type,
        "experience_required": job.experience_required,
        "salary": job.salary,
        "url": job.url,
        "source": job.source,
        "application_url": job.application_url,
    }


def _resume_summary(resume: Resume | None) -> dict:
    if resume is None:
        return {}
    return {
        "id": resume.id,
        "name": resume.name,
        "target_role": resume.target_role,
        "version": resume.version,
        "is_active": resume.is_active,
        "file_name": resume.file_name,
        "content_type": resume.content_type,
        "file_size": resume.file_size,
    }


# --------------------------------------------------------------------------
# Revalidation / actions
# --------------------------------------------------------------------------


def validate_package(db: Session, package_id: int) -> ApplicationPackage:
    """Re-run validation and refresh the gate for an existing package."""
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    if package.status in (STATUS_APPROVED, STATUS_ARCHIVED):
        return package

    job = job_service.get_job(db, package.job_id)
    profile = db.scalar(select(Profile).order_by(Profile.id).limit(1))
    resume = db.get(Resume, package.selected_resume_id) if package.selected_resume_id else None
    context = matching_service.build_user_context(db)
    answers = [
        {
            "id": a.id,
            "category": a.category,
            "question": a.question,
            "answer": a.answer,
            "source_evidence": a.source_evidence,
            "validation_status": a.validation_status,
        }
        for a in get_answers(db, package_id)
    ]
    suggestions = [
        {"requirement": s.requirement, "review_status": s.review_status}
        for s in get_suggestions(db, package_id)
    ]
    cover = None
    if package.cover_letter or package.cover_letter_status == "needs_review":
        cover = {"text": package.cover_letter, "status": package.cover_letter_status}

    findings = validation_service.validate_package_content(
        job=job,
        profile=profile,
        preferences=context.preferences,
        resume=resume,
        answers=answers,
        cover_letter=cover,
        tailoring_suggestions=suggestions,
    )
    quality = quality_service.evaluate(
        answers=answers,
        findings=findings,
        selected_resume_id=package.selected_resume_id,
        cover_letter_status=package.cover_letter_status,
        match_score=package.match_score,
    )

    _replace_findings(db, package_id, findings)
    package.quality_gate = quality.gate
    package.quality_gate_summary = quality.summary
    package.readiness = quality.readiness
    package.readiness_reasons = quality.readiness_reasons
    if package.status in (STATUS_DRAFT, STATUS_NEEDS_REVIEW, STATUS_READY_FOR_REVIEW):
        package.status = (
            STATUS_READY_FOR_REVIEW if quality.gate == "PASS" else STATUS_NEEDS_REVIEW
        )
    db.commit()
    db.refresh(package)
    return package


def update_answer(
    db: Session, package_id: int, answer_id: int, answer_text: str
) -> ApplicationAnswer:
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    if package.status == STATUS_APPROVED:
        raise PackageNotApprovableError(
            "Edited answers require revalidation -- package is approved."
        )
    answer = db.get(ApplicationAnswer, answer_id)
    if answer is None or answer.package_id != package_id:
        raise PackageNotFoundError(f"Answer {answer_id} not found in package {package_id}")
    answer.answer = answer_text
    answer.validation_status = "NEEDS_REVIEW"
    answer.feedback = "Manually edited; revalidation required."
    db.commit()
    db.refresh(answer)
    return answer


def update_cover_letter(
    db: Session, package_id: int, letter_text: str | None
) -> ApplicationPackage:
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    package.cover_letter = letter_text or None
    package.cover_letter_status = (
        "needs_review" if letter_text and letter_text.strip() else "skipped"
    )
    db.commit()
    db.refresh(package)
    return package


def approve_package(db: Session, package_id: int) -> ApplicationPackage:
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    if package.quality_gate == "FAIL":
        raise PackageNotApprovableError(
            "Package failed validation and cannot be approved without edits."
        )
    package.status = STATUS_APPROVED
    db.commit()
    db.refresh(package)
    return package


def archive_package(db: Session, package_id: int) -> ApplicationPackage:
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    package.status = STATUS_ARCHIVED
    db.commit()
    db.refresh(package)
    return package


async def regenerate_package(
    db: Session, package_id: int, *, include_cover_letter: bool | None = None
) -> ApplicationPackage:
    """Create a new version for the same job; prior versions are untouched."""
    package = get_package(db, package_id)
    if package is None:
        raise PackageNotFoundError(f"Package {package_id} not found")
    if include_cover_letter is None:
        include_cover_letter = package.cover_letter_status not in ("skipped",)
    return await prepare_package(
        db, package.job_id, include_cover_letter=include_cover_letter, force=True
    )


def _replace_findings(db: Session, package_id: int, findings) -> None:
    existing = list(
        db.scalars(
            select(ApplicationValidationFinding).where(
                ApplicationValidationFinding.package_id == package_id
            )
        )
    )
    for row in existing:
        db.delete(row)
    db.flush()
    for finding in findings:
        db.add(
            ApplicationValidationFinding(
                package_id=package_id,
                section=finding.section,
                check=finding.check,
                status=finding.status,
                message=finding.message,
            )
        )


def _float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
