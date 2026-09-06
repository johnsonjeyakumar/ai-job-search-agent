"""Truthfulness and consistency validation for application packages (Phase 6).

Every answer, cover letter, and the package as a whole is checked against the
real stored profile/resume/preferences. The engine never auto-corrects a
fact; it only reports findings (PASS / WARN / NEEDS_REVIEW / INVALID / FAIL)
so a human decides. AI findings are validated against ``AIValidationFinding``
(``extra="forbid"``) before merging.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.job import Job
from app.models.preferences import Preferences
from app.models.profile import Profile
from app.models.resume import Resume
from app.services import requirement_extractor as rex
from app.services import skill_normalizer as norm
from app.services.application_truthfulness import (
    known_certifications,
    known_companies,
    known_locations,
    known_skills,
    year_claims,
)

PASS = "PASS"
WARN = "WARN"
NEEDS_REVIEW = "NEEDS_REVIEW"
INVALID = "INVALID"
FAIL = "FAIL"


@dataclass
class ValidationFinding:
    section: str
    check: str
    status: str = NEEDS_REVIEW
    message: str = ""
    answer_id: int | None = None


def validate_package_content(
    job: Job,
    profile: Profile | None,
    preferences: Preferences | None,
    resume: Resume | None,
    answers: list[dict],
    cover_letter: dict | None,
    tailoring_suggestions: list[dict],
) -> list[ValidationFinding]:
    """Validate drafted content before it can be approved."""
    findings: list[ValidationFinding] = []
    known = known_skills(profile, resume)
    certs = known_certifications(profile)
    companies = known_companies(profile)
    locations = known_locations(profile, preferences)
    exp = _experience_window(profile, preferences)
    degree_level = _degree_level(profile)
    degree_text = profile.degree if profile is not None else None
    job_company = norm_n(job.company) if job is not None and job.company else None

    for answer in answers:
        findings.extend(
            _validate_answer(
                answer, known, certs, companies, locations, exp,
                degree_level, degree_text, job_company,
            )
        )

    if cover_letter and cover_letter.get("text"):
        findings.extend(
            _validate_text(
                "cover letter",
                cover_letter["text"],
                known, certs, companies, locations, exp,
                degree_level, degree_text, job_company,
            )
        )
    if cover_letter and cover_letter.get("status") == "needs_review":
        findings.append(
            ValidationFinding(
                section="cover letter",
                check="cover_letter.needs_review",
                status=NEEDS_REVIEW,
                message="Cover letter was flagged for review.",
            )
        )

    if resume is None:
        findings.append(
            ValidationFinding(
                section="package",
                check="selected_resume",
                status=NEEDS_REVIEW,
                message="No resume was selected for this package.",
            )
        )
    for suggestion in tailoring_suggestions:
        if suggestion.get("review_status") == "NEEDS_USER_REVIEW":
            findings.append(
                ValidationFinding(
                    section="tailoring",
                    check="suggestion.needs_user_review",
                    status=NEEDS_REVIEW,
                    message=(
                        f"Tailoring suggestion for '{suggestion.get('requirement')}' "
                        "requires user review before wording can be added."
                    ),
                )
            )
    return findings


def _validate_answer(
    answer: dict,
    known: set[str],
    certs: set[str],
    companies: set[str],
    locations: set[str],
    exp: tuple[int, int | None] | None,
    degree_level: int | None,
    degree_text: str | None,
    job_company: str | None,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    text = answer.get("answer")
    check_name = f"answer.{answer.get('category')}"
    if not text or not text.strip():
        findings.append(
            ValidationFinding(
                section="answers",
                check=check_name,
                status=INVALID if answer.get("validation_status") == "INVALID" else NEEDS_REVIEW,
                message=f"Answer for '{answer.get('category')}' is missing; user data required.",
            )
        )
        return findings
    findings.extend(
        _validate_text(
            check_name, text, known, certs, companies, locations, exp,
            degree_level, degree_text, job_company,
        )
    )
    return findings


def _validate_text(
    section: str,
    text: str,
    known: set[str],
    certs: set[str],
    companies: set[str],
    locations: set[str],
    exp: tuple[int, int | None] | None,
    degree_level: int | None,
    degree_text: str | None,
    job_company: str | None,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    lowered = text.lower()

    years = year_claims(text)
    if years and exp is not None:
        lo, hi = exp
        top = hi if hi is not None else lo
        claimed = max(years)
        if claimed > (top if top is not None else claimed):
            findings.append(
                ValidationFinding(
                    section=section,
                    check="experience",
                    status=INVALID,
                    message=(
                        f"Claims {claimed}+ years but the profile indicates up to {top} "
                        "years -- this is contradictory."
                    ),
                )
            )
        elif claimed > lo and hi is None:
            findings.append(
                ValidationFinding(
                    section=section,
                    check="experience",
                    status=NEEDS_REVIEW,
                    message=f"Claims {claimed} years; profile states {lo}+ years.",
                )
            )

    seen_terms: set[str] = set()
    for term in sorted(set(rex._TECH_TERMS), key=len, reverse=True):
        if not term:
            continue
        canonical = norm.canonicalize(term)
        if canonical in seen_terms:
            continue
        seen_terms.add(canonical)
        if _mentions_term(term, lowered) and canonical not in known:
            findings.append(
                ValidationFinding(
                    section=section,
                    check="skill_claim",
                    status=NEEDS_REVIEW,
                    message=f"Mentions '{term}' which is not in the stored skills.",
                )
            )

    if "certif" in lowered:
        known_cert_text = " ".join(certs)
        found = False
        for candidate in __CERT_TERMS:
            if candidate.lower() in lowered:
                found = candidate.lower() in known_cert_text
                break
        if not found:
            findings.append(
                ValidationFinding(
                    section=section,
                    check="certification_claim",
                    status=NEEDS_REVIEW,
                    message="Mentions a certification not present in the profile.",
                )
            )

    employer = _EMPLOYER_PATTERN.search(text)
    if employer and not any(
        company and _contains(company, lowered) for company in companies
    ):
        named = employer.group(1).strip()
        if not (job_company and _contains(norm_n(named), job_company)):
            findings.append(
                ValidationFinding(
                    section=section,
                    check="employer_claim",
                    status=NEEDS_REVIEW,
                    message=(
                        f"Names employer '{named}' not present "
                        "in stored internships."
                    ),
                )
            )

    for city, name in __INDIAN_CITIES:
        if len(city) < 4 or city not in lowered:
            continue
        if not any(_contains(city, loc) or _contains(norm_n(name), loc) for loc in locations):
            findings.append(
                ValidationFinding(
                    section=section,
                    check="location_claim",
                    status=NEEDS_REVIEW,
                    message=f"Mentions location {name} not in stored locations.",
                )
            )

    if degree_level is not None:
        claimed = _claimed_degree_level(lowered)
        if claimed is not None and claimed > degree_level:
            findings.append(
                ValidationFinding(
                    section=section,
                    check="education_claim",
                    status=NEEDS_REVIEW,
                    message=(
                        "Claims a higher degree than the profile holds "
                        f"({_degree_label(claimed)} vs stored '{degree_text or 'unknown'}')."
                    ),
                )
            )
    return findings


def _claimed_degree_level(text: str) -> int | None:
    best: int | None = None
    for key, level in rex._DEGREE_KEYWORDS.items():
        if key and key in text and (best is None or level > best):
            best = level
    return best


def _degree_label(level: int) -> str:
    inverse = {v: k for k, v in rex._DEGREE_KEYWORDS.items()}
    return inverse.get(level, f"level-{level}")


def _degree_level(profile: Profile | None) -> int | None:
    if profile is None or not profile.degree:
        return None
    value = profile.degree.lower()
    best: int | None = None
    for key, level in rex._DEGREE_KEYWORDS.items():
        if key and _contains(key, value) and (best is None or level > best):
            best = level
    return best


__CERT_TERMS = (
    "aws certified",
    "oracle certified",
    "microsoft certified",
    "azure certified",
    "ccna",
    "ocp",
    "nse",
)

__INDIAN_CITIES = sorted(rex._INDIAN_CITIES.items(), key=lambda kv: -len(kv[0]))[:15]


_EMPLOYER_PATTERN = re.compile(
    r"\b(?:worked\s+(?:at|for|with)|"
    r"intern(?:ed|ship)?\s+(?:at|with|for)|"
    r"employed\s+(?:at|with|by)|"
    r"currently\s+working\s+(?:at|with)|"
    r"was\s+(?:hired|posted)\s+(?:at|by)|"
    r"hired\s+(?:at|by))\s+"
    r"([A-Z][A-Za-z0-9 .&'-]{2,70})",
    re.I,
)


def _experience_window(
    profile: Profile | None, preferences: Preferences | None
) -> tuple[int, int | None] | None:
    levels: list[str] = []
    if profile is not None and profile.experience_level:
        levels.append(profile.experience_level)
    elif preferences is not None and preferences.experience_levels:
        levels = list(preferences.experience_levels)
    bands = [b for lv in levels if (b := rex.parse_experience_years(lv)) is not None]
    if not bands:
        return None
    lo = min(b[0] for b in bands)
    hi = max(b[1] for b in bands if b[1] is not None) or None
    return (lo, hi)


def _contains(key: str, text: str) -> bool:
    if not key:
        return False
    pattern = rf"(?<![a-z0-9+.#]){re.escape(key)}s?(?![a-z0-9+.#])"
    return re.search(pattern, text) is not None or key in text


def _mentions_term(key: str, text: str) -> bool:
    """Whole-phrase presence in cleaned text (no 'sql' inside 'postgresql')."""
    if not key:
        return False
    norm_text = norm.normalize(text)
    clean = " ".join(t.strip(".,;:()\"'") for t in norm_text.split() if t)
    phrase = re.escape(norm.normalize(key).strip(".,;:()\"'"))
    pattern = rf"(?<![a-z0-9+#.\-]){phrase}(?![a-z0-9+#.\-])"
    return re.search(pattern, clean) is not None


def norm_n(value: str) -> str:
    from app.services import skill_normalizer as norm

    return norm.normalize(value)
