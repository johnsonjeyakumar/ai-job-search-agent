"""Deterministic requirement extraction from stored job data (Phase 5).

Extracts structured signals (skills, experience, role, location, remote,
employment, education, certifications, salary) from whatever the job poster
actually provided. AI is only consulted for semantic interpretation of free
text and, because the mock provider returns nothing, the deterministic path
is the one in production. The extractor never fabricates requirements.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.job import Job
from app.services import skill_normalizer as norm

# --------------------------------------------------------------------------
# Lexicons
# --------------------------------------------------------------------------

# Technical skill terms scanned in free text. Keys are word-boundary-safe.
_TECH_TERMS: list[str] = sorted(
    {norm.normalize(t) for t in norm.CANONICAL_NAMES} | set(norm.ALIASES),
    key=len,
    reverse=True,
)

_INDIAN_CITIES: dict[str, str] = {
    "chennai": "Chennai",
    "madurai": "Madurai",
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "hyderabad": "Hyderabad",
    "pune": "Pune",
    "mumbai": "Mumbai",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "noida": "Noida",
    "gurugram": "Gurugram",
    "gurgaon": "Gurugram",
    "kolkata": "Kolkata",
    "coimbatore": "Coimbatore",
    "trichy": "Trichy",
    "trichirappalli": "Trichy",
    "erode": "Erode",
    "salem": "Salem",
    "vellore": "Vellore",
    "thanjavur": "Thanjavur",
    "tirunelveli": "Tirunelveli",
    "tiruchirappalli": "Trichy",
    "chengalpattu": "Chengalpattu",
    "kanchipuram": "Kanchipuram",
    "thoothukudi": "Thoothukudi",
    "vizag": "Visakhapatnam",
    "visakhapatnam": "Visakhapatnam",
    "ahmedabad": "Ahmedabad",
    "surat": "Surat",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
}

_DEGREE_KEYWORDS = {
    "diploma": 1,
    "b.e": 2,
    "b.e.": 2,
    "be": 2,
    "btech": 2,
    "b.tech": 2,
    "b tech": 2,
    "b.sc": 2,
    "bca": 2,
    "bachelor": 2,
    "undergraduate": 2,
    "postgraduate": 3,
    "mc a": 3,
    "mca": 3,
    "m.tech": 3,
    "mtech": 3,
    "m.sc": 3,
    "master": 3,
    "post-graduation": 3,
    "ph.d": 4,
    "phd": 4,
}

_CERT_WORDS = (
    "certification",
    "certified",
    "certificate",
    "aws certified",
    "nse",
    "ocp",
    "oracle certified",
    "ccna",
    "microsoft certified",
    "azure certified",
    "course completion",
)

_EXPERIENCE_EXTRACTORS = (
    re.compile(r"(?:min(?:imum)?\s+)?(\d{1,2})(?:\s*-\s*(\d{1,2})|\s*\+)\s*(?:years?)", re.I),
    re.compile(r"(\d{1,2})\s*(?:to|-)\s*(\d{1,2})\s*(?:years?)(?! of)", re.I),
    re.compile(
        r"(?:experience\s*(?:of\s*)?|\s)(\d{1,2})\s*(?:-\s*(\d{1,2})?)?\s*(?:years?)(?!=)",
        re.I,
    ),
    re.compile(r"\b(\d{1,2})\s*\+\s*years?\b", re.I),
    re.compile(
        r"\b(\d{1,2})(\.\d+)?\s*(?:-\s*(\d{1,2})(\.\d+)?)?\s*(?:yrs|years?)(?=\b)",
        re.I,
    ),
)

_SKILL_INTRO = re.compile(
    r"\b(knowledge of|knowledge on|hands.on with|hands on|experience with|"
    r"proficient in|proficiency in|working knowledge of|familiarity with|"
    r"good understanding of|understanding of|exposure to|skills in|"
    r"skilled at|worked on|work on|should know|must know)\s*:?\s*([^\n.,;]+)",
    re.I,
)

# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------


@dataclass
class Requirement:
    """A single extracted requirement, before profile matching."""

    term: str
    category: str  # skill|experience|role|location|remote|employment|...|salary|other
    canonical: str = ""
    source: str = "requirements"  # structured|requirements|description|title
    mandatory: bool = False
    detail: str | None = None


@dataclass
class ExtractedRequirements:
    """Everything deterministic extraction learned about a job."""

    skills: list[Requirement] = field(default_factory=list)
    roles: list[Requirement] = field(default_factory=list)
    locations: list[Requirement] = field(default_factory=list)
    remote: list[Requirement] = field(default_factory=list)
    employment: list[Requirement] = field(default_factory=list)
    education: list[Requirement] = field(default_factory=list)
    certifications: list[Requirement] = field(default_factory=list)
    experience: list[Requirement] = field(default_factory=list)
    salary: list[Requirement] = field(default_factory=list)
    other: list[Requirement] = field(default_factory=list)
    confidence: float | None = None
    ai_evidence: list[str] = field(default_factory=list)

    def all(self) -> list[Requirement]:
        return (
            self.skills
            + self.experience
            + self.roles
            + self.locations
            + self.remote
            + self.employment
            + self.education
            + self.certifications
            + self.salary
            + self.other
        )


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def extract_job_requirements(job: Job) -> ExtractedRequirements:
    """Extract structured requirements from a job posting (deterministic)."""
    bundle = ExtractedRequirements()

    for term in job.skills or []:
        bundle.skills.append(_skill_requirement(term, "structured"))

    for bullet in job.requirements or []:
        bundle.other.append(_classify_bullet(bullet, bundle, job))

    _scan_description(job.description or "", bundle)
    _scan_experience_field(job.experience_required, bundle, job)
    _scan_salary_field(job.salary, bundle)
    _scan_structured_fields(job, bundle)
    _role_from_title(job.title, bundle)

    bundle.skills = _dedupe_skills(bundle.skills)
    return bundle


async def refine_with_ai(
    job: Job, bundle: ExtractedRequirements
) -> ExtractedRequirements:
    """Consult the configured AI provider for semantic interpretation.

    Architecture rule: the LLM never emits scores. Any provider output is
    validated against ``AIJobInterpretation`` (``extra="forbid"``) before it can
    merge into the scoring input; a payload that carries ``match_score``,
    ``opportunity_score``, ``recommendation``, or anything else outside the
    structured-facts contract is rejected wholesale and we fall back to the
    deterministic bundle. ``confidence`` is recorded as metadata and never
    affects a score. The mock provider contributes nothing.
    """
    from pydantic import ValidationError

    from app.ai.registry import get_provider
    from app.schemas.ai import AIJobInterpretation

    provider = get_provider()
    if provider.name == "mock":
        return bundle
    payload = await provider.extract_job_requirements(job)
    if payload is None:
        return bundle
    try:
        interpretation = AIJobInterpretation.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return bundle

    merged = ExtractedRequirements(
        skills=list(bundle.skills),
        roles=list(bundle.roles),
        locations=list(bundle.locations),
        remote=list(bundle.remote),
        employment=list(bundle.employment),
        education=list(bundle.education),
        certifications=list(bundle.certifications),
        experience=list(bundle.experience),
        salary=list(bundle.salary),
        other=list(bundle.other),
        confidence=interpretation.confidence,
        ai_evidence=list(bundle.ai_evidence) + list(interpretation.evidence),
    )

    seen = {r.canonical for r in merged.skills}
    for term in interpretation.required_skills:
        req = _skill_requirement(term, "ai", mandatory=True)
        if req.canonical and req.canonical not in seen:
            merged.skills.append(req)
            seen.add(req.canonical)
    for term in interpretation.preferred_skills:
        req = _skill_requirement(term, "ai", mandatory=False)
        if req.canonical and req.canonical not in seen:
            merged.skills.append(req)
            seen.add(req.canonical)

    if interpretation.experience_requirement:
        merged.experience.append(
            Requirement(
                term=interpretation.experience_requirement,
                category="experience",
                source="ai",
                detail=f"Requires {interpretation.experience_requirement} (AI-interpreted)",
            )
        )

    if interpretation.role:
        merged.roles.append(
            Requirement(
                term=interpretation.role,
                canonical=norm.canonicalize(interpretation.role),
                category="role",
                source="ai",
            )
        )

    if interpretation.location:
        merged.locations.append(
            Requirement(
                term=interpretation.location,
                canonical=norm.canonicalize(interpretation.location),
                category="location",
                source="ai",
            )
        )

    if interpretation.education_requirement:
        merged.education.append(
            Requirement(
                term=_degree_text(interpretation.education_requirement.lower()),
                category="education",
                source="ai",
                detail="Education level (AI-interpreted)",
            )
        )

    for cert in interpretation.certifications:
        merged.certifications.append(
            Requirement(term=cert, category="certification", source="ai")
        )

    return merged


def _skill_requirement(term: str, source: str, mandatory: bool = False) -> Requirement:
    return Requirement(
        term=term,
        canonical=norm.canonicalize(term),
        category="skill",
        source=source,
        mandatory=mandatory,
    )


def _classify_bullet(bullet: str, bundle: ExtractedRequirements, job: Job) -> Requirement:
    """Route a requirement bullet to the right category."""
    text = (bullet or "").strip()
    if not text:
        return Requirement(term="", category="other", source="requirements")

    lower = text.lower()
    skills = _skills_in_text(text)

    years = parse_experience_years(text)
    if years is not None:
        req = Requirement(
            term=f"{years[0]}" if years[1] is None else f"{years[0]}-{years[1]}",
            category="experience",
            source="requirements",
            mandatory=_has_must(lower),
            detail=(
                f"Requires {years[0]}-{years[1]} years"
                if years[1]
                else f"Requires {years[0]}+ years"
            ),
        )
        bundle.experience.append(req)
        _attach_skills(skills, bundle, "requirements", _has_must(lower))
        return req

    if _has_degree(lower):
        req = Requirement(
            term=_degree_text(lower),
            category="education",
            source="requirements",
            mandatory=_has_must(lower),
            detail="Education level required",
        )
        bundle.education.append(req)
        _attach_skills(skills, bundle, "requirements", _has_must(lower))
        return req

    for cert in _certifications_in_text(lower):
        req = Requirement(
            term=cert,
            category="certification",
            source="requirements",
            mandatory=_has_must(lower),
            detail="Certification required" if _has_must(lower) else "Certification preferred",
        )
        bundle.certifications.append(req)

    city = _city_in_text(lower)
    if city:
        bundle.locations.append(
            Requirement(
                term=city,
                canonical=city,
                category="location",
                source="requirements",
                mandatory=_has_must(lower),
            )
        )

    if _remote_in_text(lower):
        bundle.remote.append(
            Requirement(
                term=_remote_in_text(lower),
                category="remote",
                source="requirements",
                mandatory=True,
            )
        )

    emp = _employment_in_text(lower)
    if emp:
        bundle.employment.append(
            Requirement(term=emp, category="employment", source="requirements")
        )

    if skills:
        _attach_skills(skills, bundle, "requirements", _has_must(lower))

    return Requirement(
        term=text[:200],
        canonical=norm.normalize(text)[:200],
        category="other",
        source="requirements",
        mandatory=_has_must(lower),
    )


def _attach_skills(
    skills: list[tuple[str, str]], bundle: ExtractedRequirements, source: str, mandatory: bool
) -> None:
    for term, canonical in skills:
        bundle.skills.append(
            Requirement(
                term=term,
                canonical=canonical,
                category="skill",
                source=source,
                mandatory=mandatory,
            )
        )


def _scan_description(text: str, bundle: ExtractedRequirements) -> None:
    if not text:
        return
    # Prerequisites / requirements paragraphs.
    markers = re.compile(
        r"(?:requirements?|qualifications?|skills?\s*(?:required|needed)?|"
        r"must have|you should have|you will need|what you.?ll need)(?::)?",
        re.I,
    )
    segments = re.split(markers, text)
    for segment in segments[1:]:
        chunk = segment[:3000]
        for term, canonical in _skills_in_text(chunk):
            bundle.skills.append(
                Requirement(term=term, canonical=canonical, category="skill", source="description")
            )
    # Intro-style phrases anywhere in the body.
    for match in _SKILL_INTRO.finditer(text):
        phrase = match.group(2)
        for term, canonical in _skills_in_text(phrase):
            bundle.skills.append(
                Requirement(term=term, canonical=canonical, category="skill", source="description")
            )
    # Skills mentioned in the body, even without an intro phrase.
    for term, canonical in _skills_in_text(text):
        bundle.skills.append(
            Requirement(term=term, canonical=canonical, category="skill", source="description")
        )
    # Experience phrased as free text.
    for pattern in _EXPERIENCE_EXTRACTORS:
        for match in pattern.finditer(text):
            lo_raw = match.group(1)
            if lo_raw is None:
                continue
            lo = int(lo_raw)
            hi_raw = match.group(2) or match.group(3) or match.group(4)
            hi = None
            if hi_raw:
                try:
                    hi = int(float(hi_raw))
                except (TypeError, ValueError):
                    hi = None
            term = f"{lo}" if hi is None else f"{lo}-{hi}"
            detail = f"Requires {lo}-{hi} years" if hi else f"Requires {lo}+ years"
            if all(e.term != term for e in bundle.experience):
                bundle.experience.append(
                    Requirement(
                        term=term,
                        category="experience",
                        source="description",
                        detail=detail,
                    )
                )


def _scan_experience_field(text: str | None, bundle: ExtractedRequirements, job: Job) -> None:
    parsed = parse_experience_years(text) if text else None
    if parsed is None and job.experience_required:
        lowered = norm.normalize(job.experience_required)
        if lowered in ("fresher", "fresher role", "entry level", "entry-level"):
            parsed = (0, 0)
    if parsed is not None:
        lo, hi = parsed
        bundle.experience.append(
            Requirement(
                term=f"{lo}" if hi is None else f"{lo}-{hi}",
                category="experience",
                source="structured",
                detail=f"Requires {lo}-{hi} years" if hi else f"Requires {lo}+ years",
            )
        )


def _scan_salary_field(text: str | None, bundle: ExtractedRequirements) -> None:
    parsed = parse_salary(text) if text else None
    if parsed:
        lo, hi, unit = parsed
        bundle.salary.append(
            Requirement(
                term=text or "",
                category="salary",
                source="structured",
                detail=f"{lo}-{hi} {unit}".strip(),
            )
        )


def _scan_structured_fields(job: Job, bundle: ExtractedRequirements) -> None:
    remote = _remote_from_field(job.remote_type)
    if remote:
        bundle.remote.append(
            Requirement(term=remote, category="remote", source="structured", mandatory=True)
        )
    if job.employment_type:
        bundle.employment.append(
            Requirement(
                term=job.employment_type,
                category="employment",
                source="structured",
            )
        )
    if job.location:
        city = _city_in_text(job.location.lower())
        if city:
            bundle.locations.append(
                Requirement(term=city, canonical=city, category="location", source="structured")
            )


def _role_from_title(title: str | None, bundle: ExtractedRequirements) -> None:
    if not title:
        return
    bundle.roles.append(
        Requirement(
            term=title,
            canonical=norm.normalize_role(title),
            category="role",
            source="title",
        )
    )


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------


def _skills_in_text(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    normalized = norm.normalize(text)
    for key in _TECH_TERMS:
        if not key or key in seen:
            continue
        if _word_in(key, normalized):
            canonical = norm.canonicalize(key)
            seen.add(key)
            if canonical and canonical not in [c for _, c in found]:
                found.append((canonical, canonical))
    return found


def _word_in(key: str, normalized_text: str) -> bool:
    if not key:
        return False
    pattern = rf"(?<![a-z0-9+.#]){re.escape(key)}s?(?![a-z0-9+.#])"
    return re.search(pattern, normalized_text) is not None


def parse_experience_years(text: str | None) -> tuple[int, int | None] | None:
    """Return (min, max|None) years required, or None when unspecified."""
    if not text:
        return None
    for pattern in _EXPERIENCE_EXTRACTORS:
        match = pattern.search(text)
        if match:
            lo = int(match.group(1))
            hi_raw = match.group(2) or match.group(3) or match.group(4)
            hi = None
            if hi_raw:
                try:
                    hi = int(hi_raw)
                except (TypeError, ValueError):
                    hi = None
            return (min(lo, hi) if hi is not None else lo, hi)
    lowered = norm.normalize(text)
    if lowered and any(k in lowered for k in ("fresher", "entry level", "entry-level", "freshers")):
        return (0, 0)
    return None


def parse_salary(text: str | None) -> tuple[float, float, str] | None:
    """Return (min, max, unit) yearly estimate when the salary mentions numbers."""
    if not text:
        return None
    lowered = text.lower()
    numbers = [float(m) for m in re.findall(r"\d+(?:\.\d+)?", lowered)]
    if not numbers:
        return None
    if "lpa" in lowered or "lakh" in lowered:
        unit = "LPA"
        cap = 200.0
    elif "per annum" in lowered or "annual" in lowered or "per year" in lowered:
        unit = "per annum"
        cap = 2_000_000.0
    elif "k" in lowered:
        unit = "k/year"
        cap = 1000.0
    else:
        unit = "units"
        cap = 200.0
    usable = [n for n in numbers if 1.0 <= n <= cap]
    if not usable:
        return None
    lo, hi = min(usable), max(usable)
    return (lo, hi, unit)


def _has_must(lower: str) -> bool:
    keywords = ("must have", "must be", "requires", "required", "should have", "essential")
    return any(k in lower for k in keywords)


def _has_degree(lower: str) -> bool:
    if any(
        k in lower
        for k in (
            "degree",
            "b.e",
            "b.e.",
            "btech",
            "b-tech",
            "b tech",
            "bca",
            "mca",
            "b.sc",
            "bachelor",
            "master",
            "post-graduation",
            "post graduation",
            "under graduation",
            "undergraduate",
            "diploma",
            "ph.d",
            "phd",
        )
    ):
        return True
    return any(f"{k} " in f" {lower} " or lower.endswith(k) for k in _DEGREE_KEYWORDS)


def _degree_text(lower: str) -> str:
    for key, level in sorted(_DEGREE_KEYWORDS.items(), key=lambda kv: -len(kv[0])):
        if key in lower:
            if level <= 1:
                return "Diploma"
            if level <= 2:
                return "Bachelor's degree"
            if level <= 3:
                return "Master's degree"
            return "Doctorate"
    return "Degree"


def _degree_level_int(text: str | None) -> int | None:
    """Map a degree text to a level: 1 diploma, 2 bachelor, 3 master, 4 phd."""
    if not text:
        return None
    lowered = norm.normalize(text)
    for key, level in sorted(_DEGREE_KEYWORDS.items(), key=lambda kv: -len(kv[0])):
        if key == lowered or f" {key}" in f" {lowered} " or lowered.startswith(key):
            return level
    return None


def _certifications_in_text(lower: str) -> list[str]:
    found = []
    cert_terms = (
        "AWS Certified",
        "Oracle Certified",
        "Microsoft Certified",
        "Azure Certified",
        "CCNA",
        "OCP",
        "NSE",
    )
    for term in cert_terms:
        if term.lower() in lower and term not in found:
            found.append(term)
    if "certification" in lower or "certified" in lower:
        if "any certification" not in lower and "certifications" in lower:
            found.append("Relevant certification")
    return found


_CITY_KEYS = sorted(_INDIAN_CITIES, key=len, reverse=True)


def _city_in_text(lower: str) -> str | None:
    for key in _CITY_KEYS:
        if len(key) >= 4 and key in lower:
            return _INDIAN_CITIES[key]
    for key, name in _INDIAN_CITIES.items():
        if key in lower:
            return name
    return None


def _remote_in_text(lower: str) -> str | None:
    if "work from home" in lower or "wfh" in lower or "remote" in lower:
        return "remote"
    if "hybrid" in lower:
        return "hybrid"
    if "onsite" in lower or "on-site" in lower or "on site" in lower or "in office" in lower:
        return "onsite"
    return None


_REMOTE_FIELD = {
    "remote": "remote",
    "work from home": "remote",
    "wfh": "remote",
    "hybrid": "hybrid",
    "on site": "onsite",
    "onsite": "onsite",
    "in office": "onsite",
}


def _remote_from_field(remote_type: str | None) -> str | None:
    if not remote_type:
        return None
    key = norm.normalize(remote_type)
    return _REMOTE_FIELD.get(key) or (key if key in ("remote", "hybrid", "onsite") else None)


def _employment_in_text(lower: str) -> str | None:
    if "full time" in lower or "full-time" in lower:
        return "full_time"
    if "part time" in lower or "part-time" in lower:
        return "part_time"
    if "intern" in lower:
        return "internship"
    if "contract" in lower:
        return "contract"
    return None


def _dedupe_skills(items: list[Requirement]) -> list[Requirement]:
    by_key: dict[str, Requirement] = {}
    order: list[str] = []
    for item in items:
        if not item.canonical:
            continue
        if item.canonical in by_key:
            existing = by_key[item.canonical]
            if item.source == "structured" or (item.mandatory and not existing.mandatory):
                by_key[item.canonical] = item
            continue
        by_key[item.canonical] = item
        order.append(item.canonical)
    return [by_key[key] for key in order]
