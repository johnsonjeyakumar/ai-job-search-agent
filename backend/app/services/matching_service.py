"""Personal Job Matching (Phase 5, v1).

Computes a PERSONAL MATCH SCORE for a job against the user's profile and
preferences. The score answers "how well does this job fit me?" and is
deliberately independent of the Phase 4 job-quality score. When the user has
no stored profile or preferences (the current dev database state), the
effective context is the application's default preferences, and signals the
app genuinely cannot measure (skills, education, certifications) are
UNKNOWN and excluded from the score rather than guessed.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config.settings import get_settings
from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.services import requirement_extractor as rex
from app.services import skill_normalizer as norm
from app.services.preferences_service import get_preferences

MATCHING_VERSION = "v1"

RECOMMENDATION_ORDER = ("APPLY_NOW", "APPLY", "REVIEW", "LOW_PRIORITY", "SKIP")

COMPONENT_LABELS = {
    "skills": "Skill fit",
    "experience": "Experience",
    "role": "Role",
    "location": "Location",
    "education": "Education",
    "remote": "Remote policy",
    "employment_type": "Employment type",
    "salary": "Salary",
    "certifications": "Certifications",
}

_STATUS_MATCHED = "MATCHED"
_STATUS_PARTIAL = "PARTIAL"
_STATUS_MISSING = "MISSING"
_STATUS_UNKNOWN = "UNKNOWN"


def band_for_score(score: float | None) -> str:
    """Map a numeric score to a recommendation band."""
    if score is None:
        return "REVIEW"
    if score >= 90:
        return "APPLY_NOW"
    if score >= 80:
        return "APPLY"
    if score >= 65:
        return "REVIEW"
    if score >= 50:
        return "LOW_PRIORITY"
    return "SKIP"


def weights() -> dict[str, float]:
    """Effective match weights normalized to sum to 1.0."""
    raw = get_settings().match_score_weights or {}
    total = sum(raw.get(k, 0.0) for k in COMPONENT_LABELS)
    if total <= 0:
        return {k: 0.0 for k in COMPONENT_LABELS}
    return {k: raw.get(k, 0.0) / total for k in COMPONENT_LABELS}


# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------


@dataclass
class UserContext:
    """Everything we know (or safely default) about the user's intent."""

    profile: Profile | None
    preferences: Preferences | None
    experience_band: tuple[int, int | None] | None
    preferred_locations: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    remote_types: list[str] = field(default_factory=list)
    employment_types: list[str] = field(default_factory=list)
    salary_range: tuple[float, float] | None = None
    skills: set[str] = field(default_factory=set)
    degree_level: int | None = None
    certifications: set[str] = field(default_factory=set)
    context_key: str = ""


def build_user_context(db) -> UserContext:
    """Build the user matching context from profile + preferences (or defaults)."""
    from app.schemas.preferences import PreferencesUpdate

    profile = _first_profile(db)
    preferences = _preferences_for(db, profile)
    defaults = PreferencesUpdate().model_dump() if preferences is None else None

    experience_band = _experience_band(
        preferences.experience_levels if preferences is not None else defaults["experience_levels"]
    )
    skills = _profile_skills(profile)
    certifications = _profile_certs(profile)

    context_key = _context_key(profile, preferences, db)

    return UserContext(
        profile=profile,
        preferences=preferences,
        experience_band=experience_band,
        preferred_locations=list(
            preferences.preferred_locations
            if preferences is not None
            else defaults["preferred_locations"]
        ),
        target_roles=list(
            preferences.target_roles if preferences is not None else defaults["target_roles"]
        ),
        remote_types=list(
            preferences.remote_types if preferences is not None else defaults["remote_types"]
        ),
        employment_types=list(
            preferences.employment_types
            if preferences is not None
            else defaults["employment_types"]
        ),
        salary_range=_preference_salary(profile, preferences),
        skills=skills,
        degree_level=_degree_level(profile),
        certifications=certifications,
        context_key=context_key,
    )


def _first_profile(db):
    from sqlalchemy import select

    from app.models.profile import Profile

    return db.scalar(select(Profile).order_by(Profile.id).limit(1))


def _preferences_for(db, profile: Profile | None) -> Preferences | None:
    if profile is None:
        return get_preferences(db)
    if get_preferences(db) is not None:
        return get_preferences(db)
    return None


def _experience_band(levels: list[str]) -> tuple[int, int | None] | None:
    bounds = []
    for level in levels or []:
        parsed = rex.parse_experience_years(level)
        if parsed is not None:
            lo, hi = parsed
            bounds.append((lo, hi if hi is not None else lo))
    if not bounds:
        return None
    lo = min(b[0] for b in bounds)
    hi = max(b[1] for b in bounds)
    return (lo, None if all(b[1] is None for b in bounds) else hi)


def _profile_skills(profile: Profile | None) -> set[str]:
    if profile is None:
        return set()
    terms: list[str] = []
    for attr in (
        "skills",
        "skills_programming",
        "skills_frameworks",
        "skills_databases",
        "skills_tools",
        "skills_other",
    ):
        terms.extend(getattr(profile, attr) or [])
    for project in profile.projects or []:
        terms.extend(project.get("technologies") or [])
    for internship in profile.internships or []:
        terms.extend(internship.get("skills") or internship.get("technologies") or [])
    return {c for t in terms if (c := norm.canonicalize(t))}


def _profile_certs(profile: Profile | None) -> set[str]:
    if profile is None:
        return set()
    certs: set[str] = set()
    for cert in profile.certifications or []:
        name = cert.get("name") or cert.get("certification") or ""
        certs.add(norm.normalize(name))
    return certs


def _degree_level(profile: Profile | None) -> int | None:
    if profile is None or not profile.degree:
        return None
    return rex._degree_level_int(profile.degree)


def _preference_salary(
    profile: Profile | None, preferences: Preferences | None
) -> tuple[float, float] | None:
    lo = None
    hi = None
    if preferences is not None:
        lo = preferences.salary_min if preferences.salary_min is not None else lo
        hi = preferences.salary_max if preferences.salary_max is not None else hi
    if profile is not None and profile.salary_preference:
        parsed = rex.parse_salary(profile.salary_preference)
        if parsed:
            plo, phi, _unit = parsed
            lo = lo if lo is not None else plo
            hi = hi if hi is not None else phi
    if lo is None and hi is None:
        return None
    return (lo if lo is not None else 0.0, hi if hi is not None else float("inf"))


def _context_key(profile: Profile | None, preferences: Preferences | None, db) -> str:
    from sqlalchemy import select

    from app.models.resume import Resume

    parts = [MATCHING_VERSION]
    parts.append(str(profile.updated_at) if profile is not None else "-")
    parts.append(str(preferences.updated_at) if preferences is not None else "-")
    last_resume = db.scalar(
        select(Resume.updated_at)
        .where(Resume.is_active)
        .order_by(Resume.updated_at.desc())
        .limit(1)
    )
    parts.append(str(last_resume) if last_resume is not None else "-")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Component results
# --------------------------------------------------------------------------


@dataclass
class ComponentResult:
    key: str
    label: str
    status: str = _STATUS_UNKNOWN
    score: int | None = None
    weight: float = 0.0
    message: str = ""
    sentiment: str = "info"  # positive | info | negative
    requirements: list[dict] = field(default_factory=list)  # per-requirement verdicts
    evidence: list[str] = field(default_factory=list)


@dataclass
class MatchComputation:
    match_score: float | None
    confidence_score: float
    matching_version: str
    components: dict[str, ComponentResult]
    matched_skills: list[str]
    partial_skills: list[str]
    missing_skills: list[str]
    matched_requirements: list[dict]
    partial_requirements: list[dict]
    missing_requirements: list[dict]
    unknown_requirements: list[dict]
    evidence: list[str]
    explanation: list[dict]
    recommendation: str
    blockers: list[str]
    context_key: str
    calculated_at: datetime


def calculate(
    db,
    job: Job,
    *,
    as_of: datetime | None = None,
    bundle: rex.ExtractedRequirements | None = None,
) -> MatchComputation:
    """Compute the personal match for a job against the current user context.

    ``bundle`` may supply AI-refined structured facts (already validated and
    merged by ``requirement_extractor.refine_with_ai``). Scoring itself never
    accepts scores from an external provider; the weighted math below is the
    only source of ``match_score`` / ``recommendation``.
    """
    clock = as_of or datetime.now(timezone.utc)
    context = build_user_context(db)
    if bundle is None:
        bundle = rex.extract_job_requirements(job)

    components: dict[str, ComponentResult] = {}
    components["skills"] = _skill_component(bundle.skills, context)
    components["experience"] = _experience_component(bundle.experience, context)
    components["role"] = _role_component(bundle.roles, context)
    components["location"] = _location_component(bundle.locations, bundle.remote, context)
    components["remote"] = _remote_component(bundle.remote, context)
    components["employment_type"] = _employment_component(bundle.employment, context)
    components["education"] = _education_component(bundle.education, context)
    components["certifications"] = _certification_component(bundle.certifications, context)
    components["salary"] = _salary_component(bundle.salary, context)

    weights_map = weights()
    numerator = 0.0
    assigned = 0.0
    for key, result in components.items():
        result.weight = weights_map.get(key, 0.0)
        if result.score is not None:
            numerator += result.score * result.weight
            assigned += result.weight
    score = round(numerator / assigned) if assigned > 0 else None

    requirements_buckets = _requirement_buckets(bundle, components)
    blockers = list(_collect_blockers(components))
    recommendation = "SKIP" if blockers else band_for_score(score)
    if score is None and not blockers:
        recommendation = "REVIEW"

    evidence = []
    explanation = []
    for key in COMPONENT_LABELS:
        result = components[key]
        explanation.append(
            {
                "label": result.label,
                "key": key,
                "score": result.score,
                "status": result.status,
                "message": result.message,
                "sentiment": result.sentiment,
            }
        )
        if result.status == _STATUS_UNKNOWN:
            continue
        evidence.extend(result.evidence)

    for blocker in blockers:
        explanation.append(
            {
                "label": "Blocker",
                "key": "blocker",
                "score": None,
                "status": "BLOCKED",
                "message": blocker,
                "sentiment": "blocker",
            }
        )

    return MatchComputation(
        match_score=score,
        confidence_score=round(assigned, 4),
        matching_version=MATCHING_VERSION,
        components=components,
        matched_skills=[
            e["term"] for e in requirements_buckets.matched if e["category"] == "skill"
        ],
        partial_skills=[
            e["term"] for e in requirements_buckets.partial if e["category"] == "skill"
        ],
        missing_skills=[
            e["term"] for e in requirements_buckets.missing if e["category"] == "skill"
        ],
        matched_requirements=requirements_buckets.matched,
        partial_requirements=requirements_buckets.partial,
        missing_requirements=requirements_buckets.missing,
        unknown_requirements=requirements_buckets.unknown,
        evidence=evidence,
        explanation=explanation,
        recommendation=recommendation,
        blockers=blockers,
        context_key=context.context_key,
        calculated_at=clock,
    )


async def calculate_with_ai(
    db,
    job: Job,
    *,
    as_of: datetime | None = None,
) -> MatchComputation:
    """AI-aware match computation: interpret, validate, then score.

    Structured facts from the provider are validated against the Pydantic
    contract (``refine_with_ai``) and merged deterministically; rejected or
    unavailable output falls back to the deterministic extractor. The score
    always comes from ``calculate``, never from the provider.
    """
    bundle = await rex.refine_with_ai(job, rex.extract_job_requirements(job))
    return calculate(db, job, as_of=as_of, bundle=bundle)


# --------------------------------------------------------------------------
# Component evaluators
# --------------------------------------------------------------------------


def _skill_component(
    skill_reqs: list[rex.Requirement], context: UserContext
) -> ComponentResult:
    result = ComponentResult(key="skills", label=COMPONENT_LABELS["skills"])
    if not skill_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Job does not list concrete skills"
        return result
    if context.profile is None:
        result.status = _STATUS_UNKNOWN
        result.message = "No profile on file to compare skills"
        return result
    matched, missing = 0, 0
    for req in skill_reqs:
        verdict = _STATUS_MATCHED if req.canonical in context.skills else _STATUS_MISSING
        result.requirements.append(
            {
                "term": req.term,
                "category": "skill",
                "status": verdict,
                "reason": (
                    "Skill present in profile"
                    if verdict == _STATUS_MATCHED
                    else "Skill not found in profile"
                ),
                "source": req.source,
            }
        )
        if verdict == _STATUS_MATCHED:
            matched += 1
            result.evidence.append(f"Profile includes {req.canonical}")
        else:
            missing += 1
            result.evidence.append(f"Profile does not list {req.canonical}")
    total = matched + missing
    result.score = round(100 * matched / total) if total else None
    result.status = _component_status(matched, missing, 0, total)
    result.sentiment = _sentiment(result.status)
    result.message = (
        f"{matched}/{total} required skills matched"
        if result.status != _STATUS_UNKNOWN
        else result.message
    )
    return result


def _experience_component(
    exp_reqs: list[rex.Requirement], context: UserContext
) -> ComponentResult:
    result = ComponentResult(key="experience", label=COMPONENT_LABELS["experience"])
    if not exp_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Job does not state experience"
        return result
    if context.experience_band is None:
        result.status = _STATUS_UNKNOWN
        result.message = "User experience unknown"
        return result
    (user_min, user_max) = context.experience_band
    user_top = user_max if user_max is not None else user_min
    for req in exp_reqs:
        parsed = rex.parse_experience_years(req.term) or rex.parse_experience_years(
            req.detail or ""
        )
        if parsed is None:
            result.requirements.append(
                {
                    "term": req.term,
                    "category": "experience",
                    "status": _STATUS_UNKNOWN,
                    "reason": "Cannot parse years",
                    "source": req.source,
                }
            )
            continue
        (job_min, job_max) = parsed
        if job_min > user_top:
            verdict = _STATUS_MISSING
            reason = f"Requires {job_min}+ years; candidate indicates up to {user_top} years"
            result.evidence.append(reason)
            result.blocked = True
        elif job_max is not None and job_max <= user_min:
            verdict = _STATUS_MATCHED
            reason = f"Candidate ({user_min}-{user_top}y) covers required {job_min}-{job_max}y"
            result.evidence.append(reason)
        elif job_max is not None and job_max <= user_top:
            verdict = _STATUS_PARTIAL
            reason = f"Candidate exceeds the required {job_min}-{job_max}y window"
            result.evidence.append(reason)
        elif job_min <= user_top:
            verdict = _STATUS_PARTIAL
            reason = f"Requirement tops out beyond candidate's ~{user_top} years"
            result.evidence.append(reason)
        else:
            verdict = _STATUS_PARTIAL
            reason = f"Overlapping experience ({job_min}-{job_max} vs {user_min}-{user_top})"
            result.evidence.append(reason)
        result.requirements.append(
            {
                "term": req.term,
                "category": "experience",
                "status": verdict,
                "reason": reason,
                "source": req.source,
            }
        )
    verdicts = [e["status"] for e in result.requirements if e["status"] != _STATUS_UNKNOWN]
    if not verdicts:
        result.status = _STATUS_UNKNOWN
    elif _STATUS_MISSING not in verdicts and _STATUS_PARTIAL not in verdicts:
        result.status = _STATUS_MATCHED
        result.score = 100
    elif _STATUS_MISSING in verdicts:
        result.status = _STATUS_MISSING
        result.score = 0
    else:
        result.status = _STATUS_PARTIAL
        result.score = 80
    result.sentiment = _sentiment(result.status)
    if result.status == _STATUS_MATCHED:
        result.message = "Fits your experience"
    elif result.status == _STATUS_MISSING:
        result.message = "Asks for more experience than you have"
    else:
        result.message = "Partially matches experience"
    return result


def _role_component(role_reqs: list[rex.Requirement], context: UserContext) -> ComponentResult:
    result = ComponentResult(key="role", label=COMPONENT_LABELS["role"])
    if not role_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "No job title on record"
        return result
    if not context.target_roles:
        result.status = _STATUS_UNKNOWN
        result.message = "No preferred roles on file"
        return result
    title = role_reqs[0].term
    title_key = norm.normalize_role(title)
    best = 40
    best_role = ""
    for role in context.target_roles:
        role_key = norm.normalize_role(role)
        if title_key == role_key:
            best = 100
            best_role = role
            break
        if title_key.startswith(role_key) or role_key.startswith(title_key):
            if best < 95:
                best = 95
                best_role = role
            continue
        overlap = len(set(title_key.split()) & set(role_key.split()))
        if overlap:
            if best < 80:
                best = 80
                best_role = role
        elif _tech_family(title) and _tech_family(role):
            if best < 60:
                best = 60
                best_role = role
    result.requirements.append(
        {
            "term": title,
            "category": "role",
            "status": _component_status_for_score(best),
            "reason": f"Best match against preferred role: {best_role or 'none'}",
            "source": "title",
        }
    )
    result.score = best
    result.status = _component_status_for_score(best)
    result.sentiment = _sentiment(result.status)
    result.message = (
        f"Recognized as {best_role}"
        if best >= 80
        else (
            f"Closest target role: {best_role or 'none'}"
            if best >= 60
            else "Role not in your target list yet"
        )
    )
    if best_role:
        result.evidence.append(f"Title maps to target role: {best_role}")
    return result


def _location_component(
    loc_reqs: list[rex.Requirement],
    remote_reqs: list[rex.Requirement],
    context: UserContext,
) -> ComponentResult:
    result = ComponentResult(key="location", label=COMPONENT_LABELS["location"])
    cities = sorted({r.canonical or r.term for r in loc_reqs if r.term})
    is_remotable = any(r.term in ("remote", "hybrid") for r in remote_reqs)
    if not cities and not is_remotable:
        result.status = _STATUS_UNKNOWN
        result.message = "Job location not specified"
        return result
    if not context.preferred_locations:
        result.status = _STATUS_UNKNOWN
        result.message = "No preferred locations on file"
        return result
    preferred = {norm.normalize(c) for c in context.preferred_locations}
    city_keys = {norm.normalize(c) for c in cities}
    remote_ok = any(
        "remote" in norm.normalize(c) for c in context.preferred_locations
    )
    in_pref = city_keys & preferred
    if in_pref:
        score, status = 100, _STATUS_MATCHED
        message = "Job location is among your preferred locations"
    elif is_remotable and remote_ok:
        score, status = 100, _STATUS_MATCHED
        message = "Remote option aligns with your location preferences"
    elif is_remotable:
        score, status = 70, _STATUS_PARTIAL
        message = "Remote/hybrid role; no explicit remote preference from you"
    else:
        score, status = 60, _STATUS_PARTIAL
        message = "Location not in your preferred list (relocation willingness unstated)"
    result.score = score
    result.status = status
    result.message = message
    result.sentiment = _sentiment(status)
    if cities:
        result.evidence.append(f"Job located in: {', '.join(cities)}")
    for city in cities:
        result.requirements.append(
            {
                "term": city,
                "category": "location",
                "status": (
                    _STATUS_MATCHED if norm.normalize(city) in preferred else _STATUS_PARTIAL
                ),
                "reason": (
                    "In preferred locations"
                    if norm.normalize(city) in preferred
                    else "Not a preferred location"
                ),
                "source": "location",
            }
        )
    return result


def _remote_component(remote_reqs: list[rex.Requirement], context: UserContext) -> ComponentResult:
    result = ComponentResult(key="remote", label=COMPONENT_LABELS["remote"])
    if not remote_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Job does not state remote policy"
        return result
    job_policy = remote_reqs[0].term
    if not context.remote_types:
        result.status = _STATUS_UNKNOWN
        result.message = "No remote preference on file"
        return result
    # "All types allowed" is the app default; anything the job offers is fine.
    if {"remote", "hybrid", "onsite"} <= {norm.normalize(t) for t in context.remote_types} or (
        set(context.remote_types) == {"remote", "hybrid", "onsite"}
    ):
        result.score = 100
        result.status = _STATUS_MATCHED
        result.message = f"Job is {job_policy}; your preferences allow all work policies"
    else:
        preferred = {norm.normalize(t) for t in context.remote_types}
        if job_policy in preferred:
            result.score = 100
            result.status = _STATUS_MATCHED
            result.message = "Matches your work-mode preference"
        elif job_policy == "hybrid":
            result.score = 80
            result.status = _STATUS_PARTIAL
            result.message = "Hybrid role; you preferred a different mode"
        else:
            result.score = 40
            result.status = _STATUS_MISSING
            result.message = "Work mode does not match your preference"
    result.sentiment = _sentiment(result.status)
    result.requirements.append(
        {
            "term": job_policy,
            "category": "remote",
            "status": result.status,
            "reason": result.message,
            "source": remote_reqs[0].source,
        }
    )
    return result


def _employment_component(
    emp_reqs: list[rex.Requirement], context: UserContext
) -> ComponentResult:
    result = ComponentResult(key="employment_type", label=COMPONENT_LABELS["employment_type"])
    if not emp_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Job does not state employment type"
        return result
    job_type = emp_reqs[0].term
    if (
        not context.employment_types
        or set(context.employment_types) == {"full_time", "part_time", "contract", "internship"}
    ):
        result.score = 100
        result.status = _STATUS_MATCHED
        result.message = f"{job_type} role accepted by your preferences"
    elif job_type in context.employment_types:
        result.score = 100
        result.status = _STATUS_MATCHED
        result.message = "Employment type matches your preferences"
    else:
        result.score = 30
        result.status = _STATUS_MISSING
        result.message = "Employment type not in your preferences"
    result.sentiment = _sentiment(result.status)
    result.requirements.append(
        {
            "term": job_type,
            "category": "employment",
            "status": result.status,
            "reason": result.message,
            "source": emp_reqs[0].source,
        }
    )
    return result


def _education_component(
    edu_reqs: list[rex.Requirement], context: UserContext
) -> ComponentResult:
    result = ComponentResult(key="education", label=COMPONENT_LABELS["education"])
    if not edu_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Job does not require a specific education level"
        return result
    if context.degree_level is None:
        result.status = _STATUS_UNKNOWN
        result.message = "No education on profile to compare"
        return result
    needed_level = _education_level_int(edu_reqs[0].term)
    qualified = context.degree_level >= needed_level
    for req in edu_reqs:
        needed = _education_level_int(req.term)
        result.requirements.append(
            {
                "term": req.term,
                "category": "education",
                "status": _STATUS_MATCHED if context.degree_level >= needed else _STATUS_PARTIAL,
                "reason": (
                    f"Profile level {context.degree_level} meets required {needed}"
                    if context.degree_level >= needed
                    else f"Profile level {context.degree_level} is below required {needed}"
                ),
                "source": req.source,
            }
        )
    result.score = 100 if qualified else 60
    result.status = _STATUS_MATCHED if qualified else _STATUS_PARTIAL
    result.sentiment = _sentiment(result.status)
    result.message = "Education level qualifies" if qualified else "Education below required level"
    return result


def _certification_component(
    cert_reqs: list[rex.Requirement], context: UserContext
) -> ComponentResult:
    result = ComponentResult(key="certifications", label=COMPONENT_LABELS["certifications"])
    if not cert_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Job does not require certifications"
        return result
    if context.profile is None:
        result.status = _STATUS_UNKNOWN
        result.message = "No profile to compare certifications"
        return result
    matched, missing = 0, 0
    for req in cert_reqs:
        key = norm.normalize(req.term)
        verdict = _STATUS_MATCHED if key in context.certifications else _STATUS_MISSING
        result.requirements.append(
            {
                "term": req.term,
                "category": "certification",
                "status": verdict,
                "reason": (
                    "Certification found in profile"
                    if verdict == _STATUS_MATCHED
                    else "Certification not found"
                ),
                "source": req.source,
            }
        )
        if verdict == _STATUS_MATCHED:
            matched += 1
        else:
            missing += 1
    result.score = round(100 * matched / (matched + missing)) if matched + missing else None
    result.status = _component_status(matched, missing, 0, matched + missing)
    result.sentiment = _sentiment(result.status)
    result.message = (
        f"{matched}/{matched + missing} certifications matched"
        if result.status != _STATUS_UNKNOWN
        else result.message
    )
    return result


def _salary_component(
    salary_reqs: list[rex.Requirement], context: UserContext
) -> ComponentResult:
    result = ComponentResult(key="salary", label=COMPONENT_LABELS["salary"])
    if not salary_reqs:
        result.status = _STATUS_UNKNOWN
        result.message = "Salary not listed"
        return result
    if context.salary_range is None:
        result.status = _STATUS_UNKNOWN
        result.message = "No salary expectation on file"
        return result
    got = None
    for req in salary_reqs:
        parsed = rex.parse_salary(req.detail or req.term)
        if parsed:
            lo, hi, _unit = parsed
            got = (lo, hi if hi is not None else lo)
            break
    if got is None:
        result.status = _STATUS_UNKNOWN
        result.message = "Salary range could not be parsed"
        return result
    (user_min, user_max) = context.salary_range
    (job_min, job_max) = got
    if job_max < user_min:
        score, status = 30, _STATUS_MISSING
        message = "Listed salary is below your expectation"
    else:
        score, status = 100, _STATUS_MATCHED
        message = "Listed salary meets your expectation"
    result.score = score
    result.status = status
    result.sentiment = _sentiment(status)
    result.evidence.append(message)
    result.requirements.append(
        {
            "term": salary_reqs[0].term[:100],
            "category": "salary",
            "status": status,
            "reason": message,
            "source": "structured",
        }
    )
    return result


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _component_status(matched: int, missing: int, partial: int, total: int) -> str:
    if total <= 0:
        return _STATUS_UNKNOWN
    if missing == 0 and partial == 0:
        return _STATUS_MATCHED
    if matched == 0:
        return _STATUS_MISSING
    return _STATUS_PARTIAL


def _component_status_for_score(score: int) -> str:
    if score >= 80:
        return _STATUS_MATCHED
    if score >= 60:
        return _STATUS_PARTIAL
    return _STATUS_MISSING


def _sentiment(status: str) -> str:
    if status == _STATUS_MATCHED:
        return "positive"
    if status == _STATUS_MISSING:
        return "negative"
    return "info"


_TECH_HINT = re.compile(
    r"(software|engineer|developer|junior|full.?stack|frontend|backend|"
    r"java|react|python|dev|support|tester|qa|analyst|tech|systems|"
    r"programmer|code|web|it|infra|devops|sre|data|application)",
    re.I,
)


def _tech_family(term: str) -> bool:
    if not term:
        return False
    return _TECH_HINT.search(term) is not None


def _education_level_int(text: str) -> int:
    lowered = norm.normalize(text)
    for key, level in sorted(rex._DEGREE_KEYWORDS.items(), key=lambda kv: -len(kv[0])):
        if key == lowered or f" {key}" in f" {lowered} " or lowered.startswith(key):
            return level
    return 2


@dataclass
class _RequirementBucket:
    matched: list[dict] = field(default_factory=list)
    partial: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    unknown: list[dict] = field(default_factory=list)


def _requirement_buckets(
    bundle: rex.ExtractedRequirements, components: dict[str, ComponentResult]
) -> _RequirementBucket:
    bucket = _RequirementBucket()
    for req in bundle.all():
        component = components.get(_category_for_key(req.category))
        if component is None:
            continue
        matched_entry = None
        for entry in component.requirements:
            if entry.get("category") == req.category and (
                entry.get("term") == req.term or entry.get("term") == req.canonical
            ):
                matched_entry = entry
                break
        if matched_entry is None:
            continue
        status = matched_entry["status"]
        record = {
            "term": req.term or req.canonical,
            "category": req.category,
            "status": status,
            "reason": matched_entry.get("reason", ""),
            "source": req.source,
            "mandatory": req.mandatory,
        }
        if status == _STATUS_MATCHED:
            bucket.matched.append(record)
        elif status == _STATUS_PARTIAL:
            bucket.partial.append(record)
        elif status == _STATUS_MISSING:
            bucket.missing.append(record)
        else:
            bucket.unknown.append(record)
    return bucket


def _category_for_key(category: str) -> str:
    if category == "skill":
        return "skills"
    if category == "experience":
        return "experience"
    if category == "role":
        return "role"
    if category == "location":
        return "location"
    if category == "remote":
        return "remote"
    if category == "employment":
        return "employment_type"
    if category == "education":
        return "education"
    if category == "certification":
        return "certifications"
    if category == "salary":
        return "salary"
    return "skills"


def _collect_blockers(components: dict[str, ComponentResult]) -> list[str]:
    blockers = []
    exp_blocked = getattr(components.get("experience"), "blocked", False)
    if exp_blocked:
        blockers.append("Experience requirement exceeds what the profile indicates")
    role = components.get("role")
    if role is not None and role.status == _STATUS_MISSING and role.score == 40:
        blockers.append("Role is not in your preferred roles and shares no related family")
    return blockers
