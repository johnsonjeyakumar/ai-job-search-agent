"""Shared truthfulness helpers for the application preparation engine (Phase 6).

Everything generated for an application must be traceable to real stored data
(profile, resume, preferences). These helpers are the single place that maps
"known facts" so tailoring, answers, and cover letters never fabricate.
"""
from __future__ import annotations

import re

from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import skill_normalizer as norm


def contents_text(profile: Profile | None, resume: Resume | None) -> list[str]:
    """All factual terms the system holds about the candidate, as a list."""
    parts: list[str] = []
    if profile is not None:
        for attr in (
            "skills",
            "skills_programming",
            "skills_frameworks",
            "skills_databases",
            "skills_tools",
            "skills_other",
        ):
            parts.extend(getattr(profile, attr) or [])
        for project in profile.projects or []:
            parts.append(project.get("name") or "")
            parts.extend(project.get("technologies") or [])
            parts.append(project.get("description") or "")
        for internship in profile.internships or []:
            parts.append(internship.get("company") or "")
            parts.append(internship.get("role") or "")
            parts.extend(internship.get("skills") or internship.get("technologies") or [])
        for cert in profile.certifications or []:
            parts.append(cert.get("name") or cert.get("certification") or "")
        parts.extend(p for p in [profile.degree, profile.university, profile.experience_level] if p)
        parts.extend(profile.preferred_roles or [])
    if resume is not None:
        parts.extend(p for p in [resume.target_role, resume.name] if p)
    return parts


def known_skills(profile: Profile | None, resume: Resume | None) -> set[str]:
    terms = contents_text(profile, resume)
    return {c for t in terms if (c := norm.canonicalize(t))}


def known_certifications(profile: Profile | None) -> set[str]:
    if profile is None:
        return set()
    return {
        norm.normalize(c.get("name") or c.get("certification") or "")
        for c in profile.certifications or []
    }


def known_companies(profile: Profile | None) -> set[str]:
    if profile is None:
        return set()
    return {norm.normalize(i.get("company") or "") for i in profile.internships or []}


def known_locations(profile: Profile | None, preferences: Preferences | None) -> set[str]:
    places: set[str] = set()
    if profile is not None:
        places.update(norm.normalize(p) for p in (profile.city, profile.location or ""))
    if preferences is not None:
        places.update(norm.normalize(p) for p in (preferences.preferred_locations or []))
    return {p for p in places if p}


def asserts_new_fact(
    wording: str,
    profile: Profile | None,
    resume: Resume | None,
    supported: set[str],
) -> bool:
    """True when ``wording`` would assert something stored data cannot back."""
    lowered = wording.lower()
    known_text = norm.normalize(" ".join(contents_text(profile, resume)))
    for term in sorted(set(norm.CANONICAL_NAMES)):
        if _contains(term.lower(), lowered) and not _contains(
            term.lower(), known_text
        ) and term not in supported:
            return True
    if re.search(r"\b\d+\s*(?:to|-|\+)?\s*\d*\s*years?|years? of", lowered):
        if not any(("year" in s or "experience" in s) for s in supported):
            return True
    if "certif" in lowered and not any("certif" in s for s in supported):
        return True
    return False


def year_claims(text: str | None) -> list[int]:
    """Years explicitly claimed in ``text`` (e.g. '5+ years' -> [5])."""
    if not text:
        return []
    values: list[int] = []
    for m in re.finditer(r"(\d+)(?:\.\d+)?\s*(?:to|-|\+)?\s*\d*\s*(?:years?|yrs)", text.lower()):
        try:
            values.append(int(m.group(1)))
        except (TypeError, ValueError):
            continue
    return values


def _contains(key: str, text: str) -> bool:
    if not key:
        return False
    pattern = rf"(?<![a-z0-9+.#]){re.escape(key)}s?(?![a-z0-9+.#])"
    return re.search(pattern, text) is not None or key in text
