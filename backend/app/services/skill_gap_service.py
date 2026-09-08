"""Deterministic skill gap analysis service (Phase 11 + 11.1).

Classifies skills as MATCHED / PARTIAL / MISSING / UNKNOWN against jobs.
PARTIAL: some evidence exists but is incomplete or insufficient for MATCHED.
All computation is deterministic — no LLM involvement in classification.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume import Resume
from app.models.skill_gap import SkillGapAnalysis, SkillHistory
from app.services import requirement_extractor as rex
from app.services import skill_normalizer as norm

# ---------------------------------------------------------------------------
# Evidence hierarchy
# ---------------------------------------------------------------------------

EVIDENCE_ORDER = {
    "USER_VERIFIED": 7,
    "RESUME": 6,
    "PROFILE": 5,
    "APPLICATION_PACKAGE": 4,
    "INTERVIEW": 3,
    "JOB_REQUIREMENT": 2,
    "JOB_DESCRIPTION": 1,
    "UNKNOWN": 0,
}

# Strong evidence sources: sufficient for MATCHED classification.
# Weak evidence sources: result in PARTIAL classification.
STRONG_SOURCES = {"PROFILE", "PROJECT", "INTERNSHIP", "USER_VERIFIED"}
WEAK_SOURCES = {"RESUME", "INTERVIEW", "APPLICATION_PACKAGE"}


def _evidence_rank(source: str) -> int:
    return EVIDENCE_ORDER.get(source, 0)


# ---------------------------------------------------------------------------
# Skill collection from existing data
# ---------------------------------------------------------------------------


def _collect_profile_skills(
    profile: Profile | None,
) -> dict[str, dict]:
    """Collect all canonical skills from profile structured data (strong evidence)."""
    if profile is None:
        return {}
    skills: dict[str, dict] = {}
    for attr in (
        "skills", "skills_programming", "skills_frameworks",
        "skills_databases", "skills_tools", "skills_other",
    ):
        for raw in getattr(profile, attr) or []:
            canon = norm.canonicalize(raw)
            if canon and canon not in skills:
                skills[canon] = {
                    "skill": canon,
                    "source": "PROFILE",
                    "evidence": f"Profile lists: {raw}",
                    "confidence": "HIGH",
                    "original_term": raw,
                }
    for proj in profile.projects or []:
        for raw in proj.get("technologies") or []:
            canon = norm.canonicalize(raw)
            if canon and canon not in skills:
                skills[canon] = {
                    "skill": canon,
                    "source": "PROJECT",
                    "evidence": f"Project '{proj.get('name')}' uses {raw}",
                    "confidence": "HIGH",
                    "original_term": raw,
                }
    for intern in profile.internships or []:
        for raw in intern.get("skills") or intern.get("technologies") or []:
            canon = norm.canonicalize(raw)
            if canon and canon not in skills:
                skills[canon] = {
                    "skill": canon,
                    "source": "INTERNSHIP",
                    "evidence": f"Internship '{intern.get('company')}' used {raw}",
                    "confidence": "MEDIUM",
                    "original_term": raw,
                }
    return skills


def _collect_resume_skills(
    resume: Resume | None,
) -> dict[str, dict]:
    """Collect skills inferred from resume text (weak evidence)."""
    if resume is None:
        return {}
    skills: dict[str, dict] = {}
    for text_field in [resume.target_role, resume.name]:
        if not text_field:
            continue
        for term in norm.CANONICAL_NAMES:
            if term.lower() in text_field.lower():
                canon = norm.canonicalize(term)
                if canon and canon not in skills:
                    skills[canon] = {
                        "skill": canon,
                        "source": "RESUME",
                        "evidence": f"Resume metadata indicates {term}",
                        "confidence": "MEDIUM",
                        "original_term": term,
                    }
    return skills


def _collect_interview_skills(
    session: Session, profile_id: int,
) -> dict[str, dict]:
    """Collect skills demonstrated in interviews (weak evidence — not proof of ownership)."""
    from app.models.application import Application
    from app.models.interview import Interview, InterviewQuestion
    skills: dict[str, dict] = {}
    stmt = (
        select(Interview)
        .join(Application, Interview.application_id == Application.id)
        .where(Application.profile_id == profile_id)
        .where(Interview.outcome == "STRONG_YES")
    )
    interviews = session.scalars(stmt).all()
    for interview in interviews:
        q_stmt = select(InterviewQuestion).where(
            InterviewQuestion.interview_id == interview.id
        )
        questions = session.scalars(q_stmt).all()
        for q in questions:
            if q.source in ("JOB_REQUIREMENT", "RESUME_EVIDENCE") and q.rationale:
                for word in q.source_context.split() if q.source_context else []:
                    canon = norm.canonicalize(word)
                    if canon and canon not in skills:
                        skills[canon] = {
                            "skill": canon,
                            "source": "INTERVIEW",
                            "evidence": f"Interview mentioned: {q.rationale[:100]}",
                            "confidence": "LOW",
                            "original_term": word,
                        }
    return skills


# ---------------------------------------------------------------------------
# Skill status classification
# ---------------------------------------------------------------------------


def _classify_skill(
    canonical: str,
    strong_skills: dict[str, dict],
    weak_skills: dict[str, dict],
    job_requirements: list[rex.Requirement],
) -> dict | None:
    """Classify a single skill's status against the user's profile.

    Classification rules:
    - MATCHED: skill has strong evidence (PROFILE, PROJECT, INTERNSHIP, USER_VERIFIED)
    - PARTIAL: skill has only weak evidence (RESUME, INTERVIEW, APPLICATION_PACKAGE)
    - MISSING: job requires skill, no meaningful user evidence
    - UNKNOWN: insufficient information to determine status
    """
    req = next((r for r in job_requirements if r.canonical == canonical), None)
    if req is None:
        return None

    # Check strong evidence first → MATCHED
    if canonical in strong_skills:
        prov = strong_skills[canonical]
        return {
            "skill": canonical,
            "original_term": req.term,
            "status": "MATCHED",
            "source": prov["source"],
            "evidence": prov["evidence"],
            "confidence": prov["confidence"],
            "mandatory": req.mandatory,
            "reason": f"Skill present in profile via {prov['source']}",
        }

    # Check weak evidence → PARTIAL
    if canonical in weak_skills:
        prov = weak_skills[canonical]
        return {
            "skill": canonical,
            "original_term": req.term,
            "status": "PARTIAL",
            "source": prov["source"],
            "evidence": prov["evidence"],
            "confidence": prov["confidence"],
            "mandatory": req.mandatory,
            "reason": f"Partial evidence from {prov['source']} — not verified",
        }

    # No evidence → MISSING
    return {
        "skill": canonical,
        "original_term": req.term,
        "status": "MISSING",
        "source": "JOB_REQUIREMENT",
        "evidence": None,
        "confidence": "HIGH" if req.mandatory else "MEDIUM",
        "mandatory": req.mandatory,
        "reason": "Skill required but not found in profile",
    }


# ---------------------------------------------------------------------------
# "Why this skill matters" (deterministic)
# ---------------------------------------------------------------------------


def _build_why(
    item: dict,
    market_demand: dict,
    all_items: list[dict],
) -> dict:
    """Build deterministic 'why this skill matters' explanation."""
    skill = item["skill"]
    why_parts: list[str] = []

    # Job requirement evidence
    if item.get("mandatory"):
        why_parts.append("Required by the job (mandatory)")
    else:
        why_parts.append("Listed as a job requirement")

    # Market demand
    demand = market_demand.get(skill, {})
    freq = demand.get("frequency", 0)
    total = demand.get("total_jobs", 0)
    if freq > 0:
        why_parts.append(f"Required by {freq} of {total} target jobs")

    # User evidence summary
    if item["status"] == "MATCHED":
        why_parts.append(f"Present in your profile ({item['source']})")
    elif item["status"] == "PARTIAL":
        why_parts.append(f"Partial evidence ({item['source']}) — needs verification")
    elif item["status"] == "MISSING":
        why_parts.append("No evidence of this skill in your profile")

    # Market demand level
    level = demand.get("demand_level", "LOW")
    if level == "HIGH":
        why_parts.append("High market demand")
    elif level == "MEDIUM":
        why_parts.append("Moderate market demand")

    return {
        "skill": skill,
        "why": why_parts,
        "demand_level": level,
        "demand_frequency": freq,
        "mandatory": item.get("mandatory", False),
    }


# ---------------------------------------------------------------------------
# Market demand signals (deterministic frequency analysis)
# ---------------------------------------------------------------------------


def _compute_market_demand(
    session: Session,
    required_skills: list[rex.Requirement],
) -> dict:
    """Count how often each skill appears across all jobs."""
    all_jobs = session.scalars(select(Job)).all()
    freq: dict[str, int] = {}
    total = len(all_jobs) or 1
    for job in all_jobs:
        for req_item in (job.skills or []):
            canon = norm.canonicalize(req_item)
            if canon:
                freq[canon] = freq.get(canon, 0) + 1
    result = {}
    for req in required_skills:
        canon = req.canonical
        count = freq.get(canon, 0)
        result[canon] = {
            "frequency": count,
            "total_jobs": total,
            "demand_ratio": round(count / total, 3),
            "demand_level": (
                "HIGH" if count / total > 0.5
                else "MEDIUM" if count / total > 0.2
                else "LOW"
            ),
        }
    return result


# ---------------------------------------------------------------------------
# Skill priority (deterministic: mandatory + market demand)
# ---------------------------------------------------------------------------


def _compute_priorities(
    gap_items: list[dict],
    market_demand: dict,
) -> dict:
    """Deterministic priority: HIGH if mandatory or high-demand, MEDIUM otherwise."""
    priorities = {}
    for item in gap_items:
        skill = item["skill"]
        if item["status"] not in ("MISSING", "PARTIAL"):
            priorities[skill] = "LOW"
            continue
        demand = market_demand.get(skill, {})
        is_mandatory = item.get("mandatory", False)
        is_high_demand = demand.get("demand_level") == "HIGH"
        if is_mandatory or is_high_demand:
            priorities[skill] = "HIGH"
        else:
            priorities[skill] = "MEDIUM"
    return priorities


# ---------------------------------------------------------------------------
# Skill history tracking
# ---------------------------------------------------------------------------


def record_skill_history(
    session: Session,
    profile_id: int,
    skill: str,
    new_status: str,
    source: str,
    reason: str | None = None,
    previous_status: str | None = None,
    previous_confidence: str | None = None,
    new_confidence: str | None = None,
) -> SkillHistory:
    """Create an immutable skill history record."""
    entry = SkillHistory(
        profile_id=profile_id,
        skill=skill,
        previous_status=previous_status,
        new_status=new_status,
        previous_confidence=previous_confidence,
        new_confidence=new_confidence,
        source=source,
        reason=reason,
    )
    session.add(entry)
    session.flush()
    return entry


def get_skill_history(
    session: Session,
    profile_id: int,
    skill: str | None = None,
    limit: int = 100,
) -> list[SkillHistory]:
    """Get skill history, optionally filtered by skill name."""
    stmt = select(SkillHistory).where(SkillHistory.profile_id == profile_id)
    if skill:
        stmt = stmt.where(SkillHistory.skill == skill)
    stmt = stmt.order_by(SkillHistory.created_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def get_skill_analytics(
    session: Session,
    profile_id: int | None = None,
) -> dict:
    """Compute aggregate skill analytics across all analyses."""
    stmt = select(SkillGapAnalysis)
    if profile_id is not None:
        stmt = stmt.where(SkillGapAnalysis.profile_id == profile_id)
    analyses = list(session.scalars(stmt).all())

    matched = 0
    partial = 0
    missing = 0
    unknown = 0
    for a in analyses:
        matched += len(a.matched_skills or [])
        partial += len(a.partial_skills or [])
        missing += len(a.missing_skills or [])
        unknown += len(a.unknown_skills or [])

    # Learning progress
    from app.models.skill_gap import LearningItem, LearningPlan
    lp_stmt = select(LearningPlan)
    if profile_id is not None:
        lp_stmt = lp_stmt.where(LearningPlan.profile_id == profile_id)
    plans = list(session.scalars(lp_stmt).all())

    total_learning_items = 0
    completed_items = 0
    verified_items = 0
    in_progress_items = 0
    for plan in plans:
        items = session.scalars(
            select(LearningItem).where(LearningItem.plan_id == plan.id)
        ).all()
        total_learning_items += len(items)
        completed_items += sum(1 for i in items if i.status == "COMPLETED")
        verified_items += sum(1 for i in items if i.status == "VERIFIED")
        in_progress_items += sum(1 for i in items if i.status == "IN_PROGRESS")

    return {
        "matched_count": matched,
        "partial_count": partial,
        "missing_count": missing,
        "unknown_count": unknown,
        "total_analyses": len(analyses),
        "total_learning_items": total_learning_items,
        "completed_learning_items": completed_items,
        "verified_learning_items": verified_items,
        "in_progress_learning_items": in_progress_items,
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyze_skill_gaps(
    session: Session,
    job_id: int,
    profile_id: int | None = None,
    resume_id: int | None = None,
) -> SkillGapAnalysis:
    """Compute skill gap analysis for a job against the user's profile."""
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    profile = session.get(Profile, profile_id) if profile_id else None
    resume = session.get(Resume, resume_id) if resume_id else None

    # Extract job skill requirements
    extracted = rex.extract_job_requirements(job)
    skill_reqs = [r for r in extracted.skills if r.canonical]

    # Collect user skills — separate strong vs weak evidence
    strong_skills: dict[str, dict] = {}
    weak_skills: dict[str, dict] = {}

    strong_skills.update(_collect_profile_skills(profile))
    weak_skills.update(_collect_resume_skills(resume))

    if profile:
        interview_skills = _collect_interview_skills(session, profile.id)
        for k, v in interview_skills.items():
            if k not in strong_skills and k not in weak_skills:
                weak_skills[k] = v

    # Classify each required skill
    matched, partial, missing, unknown = [], [], [], []
    evidence_items = []
    all_classified: list[dict] = []

    for req in skill_reqs:
        item = _classify_skill(req.canonical, strong_skills, weak_skills, skill_reqs)
        if item is None:
            continue
        all_classified.append(item)
        if item["status"] == "MATCHED":
            matched.append(item)
        elif item["status"] == "PARTIAL":
            partial.append(item)
        elif item["status"] == "MISSING":
            missing.append(item)
        else:
            unknown.append(item)

    # Market demand
    market_demand = _compute_market_demand(session, skill_reqs)

    # Priorities (MISSING + PARTIAL get priority; MATCHED = LOW)
    gap_items = missing + partial
    priorities = _compute_priorities(gap_items, market_demand)

    # Attach priority to all classified items
    for item in all_classified:
        item["priority"] = priorities.get(item["skill"], "LOW")

    # Build evidence items with "why" info
    for item in all_classified:
        why = _build_why(item, market_demand, all_classified)
        evidence_items.append({
            "skill": item["skill"],
            "status": item["status"],
            "source": item["source"],
            "evidence": item["evidence"],
            "confidence": item["confidence"],
            "priority": item["priority"],
            "why": why["why"],
            "demand_level": why["demand_level"],
            "demand_frequency": why["demand_frequency"],
            "mandatory": why["mandatory"],
        })

    # Readiness: PARTIAL counts as 50% credit toward readiness
    total = len(skill_reqs) or 1
    matched_count = len(matched)
    partial_count = len(partial)
    readiness_pct = round(100 * (matched_count + 0.5 * partial_count) / total) if total else 0
    readiness_label = (
        "STRONG" if readiness_pct >= 80
        else "MODERATE" if readiness_pct >= 50
        else "WEAK" if readiness_pct > 0
        else "UNKNOWN"
    )

    # Persist
    analysis = SkillGapAnalysis(
        job_id=job_id,
        profile_id=profile_id,
        resume_id=resume_id,
        matched_skills=[i["skill"] for i in matched],
        partial_skills=[i["skill"] for i in partial],
        missing_skills=[i["skill"] for i in missing],
        unknown_skills=[i["skill"] for i in unknown],
        evidence=evidence_items,
        priorities=priorities,
        market_demand=market_demand,
        readiness_label=readiness_label,
        readiness_percentage=readiness_pct,
        readiness_breakdown={
            "matched": matched_count,
            "partial": partial_count,
            "missing": len(missing),
            "unknown": len(unknown),
            "total": len(skill_reqs),
        },
    )
    session.add(analysis)
    session.flush()

    # Record skill history for this profile
    if profile_id:
        for item in all_classified:
            record_skill_history(
                session,
                profile_id=profile_id,
                skill=item["skill"],
                new_status=item["status"],
                source=item["source"],
                reason=item["reason"],
            )

    return analysis


def get_latest_analysis(
    session: Session,
    job_id: int,
) -> SkillGapAnalysis | None:
    """Get the most recent analysis for a job."""
    stmt = (
        select(SkillGapAnalysis)
        .where(SkillGapAnalysis.job_id == job_id)
        .order_by(SkillGapAnalysis.created_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_analyses(
    session: Session,
    profile_id: int | None = None,
    limit: int = 50,
) -> list[SkillGapAnalysis]:
    """List skill gap analyses, optionally filtered by profile."""
    stmt = select(SkillGapAnalysis)
    if profile_id is not None:
        stmt = stmt.where(SkillGapAnalysis.profile_id == profile_id)
    stmt = stmt.order_by(SkillGapAnalysis.created_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())
