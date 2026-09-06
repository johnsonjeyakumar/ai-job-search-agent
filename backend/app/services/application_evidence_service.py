"""Evidence mapping for application packages (Phase 6).

Turns every extracted job requirement into an evidence entry that says what
the profile/resume/preferences actually support (MATCHED, PARTIAL,
MISSING_EVIDENCE) or whether we genuinely cannot tell (UNKNOWN). Evidence is
only ever drawn from real stored data; nothing is fabricated. Reuses the
Phase 5 match computation for requirement verdicts -- no new scoring.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import requirement_extractor as rex
from app.services import skill_normalizer as norm
from app.services.resume_selection_service import ResumeSelection

STATUS_MATCHED = "MATCHED"
STATUS_PARTIAL = "PARTIAL"
STATUS_MISSING_EVIDENCE = "MISSING_EVIDENCE"
STATUS_UNKNOWN = "UNKNOWN"

# Phase 5 match bucket names -> evidence statuses.
_BUCKET_STATUS = {
    "matched_requirements": STATUS_MATCHED,
    "partial_requirements": STATUS_PARTIAL,
    "missing_requirements": STATUS_MISSING_EVIDENCE,
    "unknown_requirements": STATUS_UNKNOWN,
}


@dataclass
class EvidenceEntry:
    requirement: str
    category: str
    status: str
    evidence: str | None = None
    source: str = "job"
    confidence: str = "LOW"
    reason: str = ""


def build_evidence_entries(
    bundle: rex.ExtractedRequirements,
    buckets: dict[str, list[dict]],
    profile: Profile | None,
    preferences: Preferences | None,
    resume: Resume | None,
    selection: ResumeSelection | None,
) -> list[EvidenceEntry]:
    """Map every requirement to its evidence status.

    ``buckets`` is the Phase 5 match computation's requirement buckets
    (matched/partial/missing/unknown lists of dicts with term/category/status).
    """
    lookup: dict[tuple[str, str], dict] = {}
    for bucket_name, status in _BUCKET_STATUS.items():
        for entry in buckets.get(bucket_name, []):
            key = ((entry.get("term") or "").lower(), (entry.get("category") or "").lower())
            lookup.setdefault(key, entry)

    entries: list[EvidenceEntry] = []
    for req in bundle.all():
        term = req.term or req.canonical
        if not term:
            continue
        key = (term.lower(), req.category.lower())
        bucket_entry = lookup.get(key)
        matched_status = (
            bucket_entry.get("status") if bucket_entry is not None else None
        )
        if matched_status in ("MATCHED", "PARTIAL", "MISSING"):
            status = {
                "MATCHED": STATUS_MATCHED,
                "PARTIAL": STATUS_PARTIAL,
                "MISSING": STATUS_MISSING_EVIDENCE,
            }[matched_status]
            reason = bucket_entry.get("reason", "")
        else:
            status = STATUS_UNKNOWN
            reason = "Cannot verify from stored data"

        entry = _enrich(req, status, reason, profile, preferences, resume)
        entries.append(entry)
    return _dedupe(entries)


def _enrich(
    req: rex.Requirement,
    status: str,
    reason: str,
    profile: Profile | None,
    preferences: Preferences | None,
    resume: Resume | None,
) -> EvidenceEntry:
    if status == STATUS_MISSING_EVIDENCE:
        return EvidenceEntry(
            requirement=req.term or req.canonical,
            category=req.category,
            status=status,
            evidence=None,
            source="profile",
            confidence="LOW",
            reason=reason or "No matching evidence in the profile or resume.",
        )
    if status == STATUS_UNKNOWN:
        return EvidenceEntry(
            requirement=req.term or req.canonical,
            category=req.category,
            status=status,
            evidence=None,
            source="job",
            confidence="MEDIUM",
            reason="The stored job data does not let us confirm this requirement.",
        )

    if req.category == "skill":
        return _skill_evidence(req, status, profile, resume)
    if req.category == "certification":
        return _cert_evidence(req, status, profile)
    if req.category == "experience":
        return _experience_evidence(req, status, profile, preferences)
    if req.category == "role":
        return _role_evidence(req, status, profile, resume)
    if req.category == "location":
        return _location_evidence(req, status, profile, preferences)
    if req.category == "remote":
        return _remote_evidence(req, status, profile, preferences)
    if req.category == "employment":
        return _employment_evidence(req, status, preferences)
    if req.category == "education":
        return _education_evidence(req, status, profile)
    return EvidenceEntry(
        requirement=req.term or req.canonical,
        category=req.category,
        status=status,
        evidence=reason or None,
        source="job",
        confidence="MEDIUM" if status == STATUS_MATCHED else "LOW",
        reason=reason,
    )


def _skill_evidence(req, status, profile, resume) -> EvidenceEntry:
    canonical = req.canonical or norm.canonicalize(req.term)
    source = "profile"
    evidence = None
    if profile is not None:
        profile_terms = _flat_profile_terms(profile)
        if canonical in profile_terms["skills"]:
            evidence = f"Profile lists the skill: {req.term}"
        for project in profile.projects or []:
            proj_tech = [t for t in (project.get("technologies") or []) if tuple]
            if any(norm.canonicalize(t) == canonical for t in proj_tech):
                evidence = f"Project '{project.get('name')}' uses {req.term}"
                source = "project"
                break
        if evidence is None:
            for internship in profile.internships or []:
                terms = internship.get("skills") or internship.get("technologies") or []
                if any(norm.canonicalize(t) == canonical for t in terms):
                    evidence = f"Internship '{internship.get('company')}' used {req.term}"
                    source = "internship"
                    break
    if evidence is None and resume is not None:
        text = f"{resume.target_role or ''} {resume.name}"
        if _contains(canonical, text):
            evidence = f"Resume metadata indicates {req.term}"
            source = "resume"
    return EvidenceEntry(
        requirement=req.term or canonical,
        category="skill",
        status=status,
        evidence=evidence,
        source=source,
        confidence="HIGH" if status == STATUS_MATCHED and evidence else "MEDIUM",
        reason="",
    )


def _cert_evidence(req, status, profile) -> EvidenceEntry:
    certs = [c.get("name") or c.get("certification") for c in (profile.certifications or [])]
    needle = norm.normalize(req.term)
    hit = next(
        (c for c in certs if c and needle in norm.normalize(c)), None
    )
    if hit and status == STATUS_MATCHED:
        return EvidenceEntry(
            requirement=req.term, category="certification", status=status,
            evidence=f"Profile lists certification: {hit}", source="certification",
            confidence="HIGH",
        )
    return EvidenceEntry(
        requirement=req.term, category="certification", status=status,
        evidence=hit and f"Profile lists certification: {hit}" or None,
        source="certification",
        confidence="HIGH" if hit else "LOW",
    )


def _experience_evidence(req, status, profile, preferences) -> EvidenceEntry:
    level = None
    if profile is not None and profile.experience_level:
        level = profile.experience_level
    elif preferences is not None and preferences.experience_levels:
        level = ", ".join(preferences.experience_levels)
    if status == STATUS_MATCHED and level:
        return EvidenceEntry(
            requirement=req.term, category="experience", status=status,
            evidence=f"Profile indicates experience: {level}", source="profile",
            confidence="HIGH",
        )
    return EvidenceEntry(
        requirement=req.term, category="experience", status=status,
        evidence=level and f"Profile indicates experience: {level}" or None,
        source="profile",
        confidence="MEDIUM" if level else "LOW",
    )


def _role_evidence(req, status, profile, resume) -> EvidenceEntry:
    roles = []
    if resume is not None and resume.target_role:
        roles.append(resume.target_role)
    if profile is not None:
        roles.extend(profile.preferred_roles or [])
    if status == STATUS_MATCHED and roles:
        return EvidenceEntry(
            requirement=req.term, category="role", status=status,
            evidence=f"Role aligned with: {', '.join(roles)}", source="resume",
            confidence="HIGH",
        )
    return EvidenceEntry(
        requirement=req.term, category="role", status=status,
        evidence=roles and f"Related to: {', '.join(roles)}" or None,
        source="resume", confidence="MEDIUM" if roles else "LOW",
    )


def _location_evidence(req, status, profile, preferences) -> EvidenceEntry:
    places = []
    if profile is not None:
        places.extend([p for p in (profile.city, profile.location, profile.state) if p])
    if preferences is not None:
        places.extend(preferences.preferred_locations or [])
    if status == STATUS_MATCHED and places:
        return EvidenceEntry(
            requirement=req.term, category="location", status=status,
            evidence=f"Profile/preferences include: {', '.join(dict.fromkeys(places))}",
            source="preferences", confidence="HIGH",
        )
    return EvidenceEntry(
        requirement=req.term, category="location", status=status,
        evidence=places and f"Profile/preferences: {', '.join(dict.fromkeys(places))}" or None,
        source="preferences", confidence="MEDIUM" if places else "LOW",
    )


def _remote_evidence(req, status, profile, preferences) -> EvidenceEntry:
    mode = None
    if profile is not None and profile.remote_preference:
        mode = profile.remote_preference
    elif preferences is not None and preferences.remote_types:
        mode = ", ".join(preferences.remote_types)
    if status == STATUS_MATCHED and mode:
        return EvidenceEntry(
            requirement=req.term, category="remote", status=status,
            evidence=f"Work-mode preference on file: {mode}", source="preferences",
            confidence="HIGH",
        )
    return EvidenceEntry(
        requirement=req.term, category="remote", status=status,
        evidence=mode and f"Work-mode preference on file: {mode}" or None,
        source="preferences", confidence="MEDIUM" if mode else "LOW",
    )


def _employment_evidence(req, status, preferences) -> EvidenceEntry:
    types = preferences.employment_types if preferences is not None else []
    hit = req.term in types or (not types and not preferences)
    if status == STATUS_MATCHED and hit:
        return EvidenceEntry(
            requirement=req.term, category="employment", status=status,
            evidence="Employment type accepted by preferences", source="preferences",
            confidence="HIGH",
        )
    return EvidenceEntry(
        requirement=req.term, category="employment", status=status,
        evidence=types and f"Preferences allow: {', '.join(types)}" or None,
        source="preferences",
        confidence="MEDIUM" if types else "LOW",
    )


def _education_evidence(req, status, profile) -> EvidenceEntry:
    if profile is None or not profile.degree:
        return EvidenceEntry(
            requirement=req.term, category="education", status=status,
            evidence=None, source="profile", confidence="LOW",
            reason="No education stored on the profile.",
        )
    parts = [profile.degree]
    if profile.university:
        parts.append(profile.university)
    text = " ".join(p for p in parts if p)
    return EvidenceEntry(
        requirement=req.term, category="education", status=status,
        evidence=f"Profile education: {text}", source="education",
        confidence="HIGH" if status == STATUS_MATCHED else "MEDIUM",
    )


def _flat_profile_terms(profile: Profile) -> dict[str, set[str]]:
    skills: set[str] = set()
    for attr in (
        "skills",
        "skills_programming",
        "skills_frameworks",
        "skills_databases",
        "skills_tools",
        "skills_other",
    ):
        for term in getattr(profile, attr) or []:
            key = norm.canonicalize(term)
            if key:
                skills.add(key)
    for project in profile.projects or []:
        for term in project.get("technologies") or []:
            key = norm.canonicalize(term)
            if key:
                skills.add(key)
    for internship in profile.internships or []:
        for term in internship.get("skills") or internship.get("technologies") or []:
            key = norm.canonicalize(term)
            if key:
                skills.add(key)
    return {"skills": skills}


def _contains(key: str, text: str) -> bool:
    if not key:
        return False
    import re

    normalized = norm.normalize(text)
    pattern = rf"(?<![a-z0-9+.#]){re.escape(key)}s?(?![a-z0-9+.#])"
    return re.search(pattern, normalized) is not None or key in normalized


def _dedupe(entries: list[EvidenceEntry]) -> list[EvidenceEntry]:
    seen: set[tuple[str, str]] = set()
    out: list[EvidenceEntry] = []
    for entry in entries:
        key = (entry.requirement.lower(), entry.category.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out
