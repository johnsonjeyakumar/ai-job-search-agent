"""Pure normalization and validation helpers for job records.

These functions are intentionally source-agnostic: concrete job sources use
them to shape their raw output into the normalized ``JobCreate`` form.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

_REMOTE_RE = re.compile(r"\b(remote|telecommute|work from home|wfh)\b", re.IGNORECASE)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE_RE = re.compile(r"\b(on.?site|in.office)\b", re.IGNORECASE)

_EMPLOYMENT_ORDER = (
    ("part", "part_time"),
    ("full", "full_time"),
    ("contract", "contract"),
    ("temporary", "contract"),
    ("intern", "internship"),
)

_EXPERIENCE_RE = re.compile(
    r"(fresher|entry level|\d+\+?\s+years?|\d+\s*-\s*\d+\s+years?)",
    re.IGNORECASE,
)

# Key-alias collections are ordered tuples: earlier entries win, deterministically.
_URL_KEYS = (
    "url",
    "link",
    "href",
    "jobUrl",
    "job_url",
    "viewjob",
    "platform_url",
    "jobPageUrl",
    "jobPostingUrl",
)
_COMPANY_URL_KEYS = (
    "companyUrl",
    "company_url",
    "companyProfileUrl",
    "employerUrl",
    "companyIndeedUrl",
)
_TITLE_KEYS = ("title", "position", "role", "jobTitle", "job_title", "heading", "jobTitleText")
_COMPANY_KEYS = (
    "company",
    "company_name",
    "employer",
    "hiringCompany",
    "organization",
    "companyName",
)
_LOCATION_KEYS = ("location", "formattedLocation", "city", "state", "country", "loc", "locale")
_DESCRIPTION_KEYS = (
    "description",
    "descriptionText",
    "fullDescription",
    "details",
    "body",
    "jobDescription",
    "job_description",
    "advertiserBranding",
)
_SALARY_KEYS = ("salary", "salaryRange", "salaryText", "compensation", "compensationRange", "pay")
# Ordered from most to least reliable. The first *parseable* concrete date
# wins; a key is only skipped when its value is empty or unparseable, so a
# relative-string first key never blocks a real date later in the list.
# Relative dates ("2 days ago") are never used to invent posted_date.
_DATE_KEYS = (
    "postingDateParsed",  # actor-provided, cleaned absolute posting date
    "postedAt",           # ISO 8601 posting timestamp
    "listedAtISO",
    "postedDate",
    "posted_date",
    "publishedAt",
    "publishDate",
    "postingDate",
    "datePosted",
    "createdAt",
)
_EXPERIENCE_KEYS = ("experienceLevel", "experience_level", "experienceRequired")
_REQUIREMENTS_KEYS = ("requirements", "qualifications")
_SKILLS_KEYS = ("skills", "skill", "skillsList")


def clean_text(value: object) -> str | None:
    """Collapse whitespace and strip; return ``None`` when effectively empty."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    text = str(value).replace("\u00a0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def clean_description(value: object) -> str | None:
    """Strip and tidy a long description while preserving paragraph breaks."""
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    # Trim trailing whitespace on each line but keep blank lines.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or None


def normalize_location(value: object) -> str | None:
    location = clean_text(value)
    if not location:
        return None
    return ", ".join(part.strip() for part in location.split(",") if part.strip())


def normalize_title(value: object) -> str | None:
    return clean_text(value)


def normalize_company(value: object) -> str | None:
    return clean_text(value)


def normalize_url(value: object) -> str | None:
    url = clean_text(value)
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url
    return None


def is_valid_url(value: object) -> bool:
    return normalize_url(value) is not None


def parse_date(value: object) -> date | None:
    """Parse a concrete posting date. Relative strings (e.g. ``2 days ago``)
    are treated as unavailable so posted_date is never invented."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value)
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed.date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(candidate).date()
    except Exception:
        return None


def classify_remote(
    raw: dict, location: str | None = None, employment_text: str | None = None
) -> str | None:
    """Classify a record as remote / hybrid / onsite from available signals."""
    signals = []
    for key in ("workplaceType", "remoteType", "workMode", "is_remote", "remote"):
        value = raw.get(key)
        if value is None:
            continue
        if value is True or (isinstance(value, str) and value.lower() in ("true", "1", "yes")):
            signals.append("remote")
            continue
        if value is False or (isinstance(value, str) and value.lower() in ("false", "0", "no")):
            signals.append("onsite")
            continue
        signals.append(str(value))
    if location:
        signals.append(location)
    if employment_text:
        signals.append(employment_text)
    joined = " ".join(signals)
    if _HYBRID_RE.search(joined):
        return "hybrid"
    if _REMOTE_RE.search(joined):
        return "remote"
    if _ONSITE_RE.search(joined):
        return "onsite"
    return None


def classify_employment(value: object) -> str | None:
    """Map common employment-type spellings to lowercase canonical tokens."""
    text = clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    for token, mapped in _EMPLOYMENT_ORDER:
        if token in lowered:
            return mapped
    return None


def _first(raw: dict, keys) -> object:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def first_date(raw: dict, keys: tuple[str, ...] = _DATE_KEYS) -> date | None:
    """Return the first concrete date among the given keys.

    Precedence follows the key order: semantically reliable posting-date fields
    are listed first. When the winning key holds an unparseable or relative
    value, the next key is tried instead. ``None`` is returned when no reliable
    concrete date exists, so posted_date is never invented.
    """
    for key in keys:
        value = raw.get(key)
        if value in (None, ""):
            continue
        parsed = parse_date(value)
        if parsed is not None:
            return parsed
    return None


def build_location(raw: dict) -> str | None:
    """Assemble a location from structured city/state/country parts."""
    parts = []
    for key in ("city", "state", "country", "location"):
        value = clean_text(raw.get(key))
        if value:
            parts.append(value)
    if not parts:
        return None
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return ", ".join(seen)


def extract_requirements(value: object, max_items: int = 30) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = [clean_text(item) for item in value]
        return [item for item in items if item][:max_items]
    text = clean_description(value)
    if not text:
        return []
    lines = [
        clean_text(line.lstrip("-•*"))
        for line in text.split("\n")
        if re.match(r"^\s*[-•*]\s", line)
    ]
    return [line for line in lines if line][:max_items]


def extract_single_item(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = [clean_text(item) for item in value]
        return [item for item in items if item]
    item = clean_text(value)
    return [item] if item else []
