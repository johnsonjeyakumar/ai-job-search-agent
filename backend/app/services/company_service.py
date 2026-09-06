"""Company intelligence built from observed job data only (Phase 4).

No web lookups and no invented facts: every stored value either comes straight
from a collected job or is an aggregate of collected jobs. Exact normalized-key
matching is used; weak name-similarity merges are deliberately avoided.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.job_sources import normalizer as norm
from app.job_sources.normalizer import clean_text
from app.models.company import Company
from app.models.job import Job

# Legal-entity suffixes that carry no distinguishing meaning for matching.
_LEGAL_SUFFIXES = (
    "pvt",
    "private",
    "limited",
    "ltd",
    "llc",
    "llp",
    "inc",
    "incorp",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
)

# Suffixes that never get stripped because they ARE part of real names.
_KEYWORD_SUFFIXES = ("technologies", "technology", "software", "systems", "labs", "group")

_NOISE_WORDS = {"the", "and", "of", "a", "an"}

# Hosts that are job marketplaces, not company-owned websites.
_MARKETPLACE_HOSTS = {
    "indeed.com",
    "www.indeed.com",
    "ca.indeed.com",
    "uk.indeed.com",
    "in.indeed.com",
    "glassdoor.com",
    "www.glassdoor.com",
    "linkedin.com",
    "www.linkedin.com",
    "naukri.com",
    "www.naukri.com",
    "monster.com",
    "www.monster.com",
    "careerbuilder.com",
    "www.careerbuilder.com",
}


def normalize_company_name(value: str | None) -> str | None:
    """Deterministic merge key: lowercase, legal suffix stripped, deduped words."""
    text = clean_text(value)
    if not text:
        return None
    words = re.sub(r"[^A-Za-z0-9]+", " ", text.lower()).split()
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    words = [word for word in words if word not in _NOISE_WORDS]
    return " ".join(words) or None


def display_name_for(value: str | None) -> str | None:
    return clean_text(value)


def _trusted_domain(company_url: str | None) -> tuple[str | None, str | None]:
    """Return (domain, website) for a trustworthy company-owned URL.

    Marketplace and aggregator hosts (Indeed, LinkedIn, Glassdoor, ...) are
    not company-owned, so they yield no domain.
    """
    url = norm.normalize_url(company_url)
    if not url:
        return None, None
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or host in _MARKETPLACE_HOSTS:
        return None, None
    # Never treat obvious profile/aggregator paths as the company homepage.
    if parsed.path.rstrip("/") in ("", "/mp", "/cmp", "/jobs"):
        return host, url
    return host, url


def get_or_create_company(
    db: Session, raw_name: str | None, *, seen_at: datetime | None = None
) -> tuple[Company | None, bool]:
    """Fetch or create the company row for a raw employer name."""
    key = normalize_company_name(raw_name)
    if not key:
        return None, False
    company = db.scalar(
        select(Company).where(Company.normalized_name == key).limit(1)
    )
    if company is not None:
        return company, False
    clock = seen_at or datetime.now(timezone.utc)
    company = Company(
        normalized_name=key,
        display_name=display_name_for(raw_name),
        first_seen_job_at=clock,
        last_seen_job_at=clock,
    )
    db.add(company)
    db.flush()
    return company, True


def upsert_company_for_job(
    db: Session, job: Job, *, seen_at: datetime | None = None
) -> Company | None:
    """Refresh company observations from one job listing."""
    company, _ = get_or_create_company(db, job.company, seen_at=seen_at)
    if company is None:
        return None
    clock = seen_at or datetime.now(timezone.utc)

    observed = display_name_for(job.company)
    if observed:
        company.display_name = observed
    if company.first_seen_job_at is None or clock < company.first_seen_job_at:
        company.first_seen_job_at = clock
    if company.last_seen_job_at is None or clock > company.last_seen_job_at:
        company.last_seen_job_at = clock

    domain, website = _trusted_domain(job.company_url)
    if domain and company.domain is None:
        company.domain = domain
    if website and company.website is None:
        company.website = website
    db.flush()
    return company


def find_company(db: Session, raw_name: str | None) -> Company | None:
    key = normalize_company_name(raw_name)
    if not key:
        return None
    return db.scalar(select(Company).where(Company.normalized_name == key).limit(1))


def job_aggregates(db: Session) -> dict[str, dict[str, object]]:
    """Per normalized-name aggregates computed from the jobs table.

    Keys are Company.normalized_name values so they map without extra lookups.
    """
    rows = db.execute(
        select(
            Job.company,
            func.count(Job.id),
            func.count(func.distinct(func.lower(Job.title))),
            func.max(Job.last_seen_at),
        ).group_by(Job.company)
    )
    src_rows = db.execute(
        select(Job.company, Job.source).distinct()
    ).all()

    counts: dict[str, dict[str, object]] = {}
    for company_name, count, distinct_roles, last_seen in rows:
        key = normalize_company_name(company_name)
        if not key:
            continue
        counts[key] = {
            "active_job_count": int(count),
            "distinct_role_count": int(distinct_roles),
            "last_seen_job_at": last_seen,
            "sources": set(),
        }
    for company_name, src in src_rows:
        key = normalize_company_name(company_name)
        if key and key in counts:
            counts[key]["sources"].add(src)
    for entry in counts.values():
        entry["source_count"] = len(entry["sources"])
    return counts


def company_view(db: Session, company: Company | None) -> dict | None:
    """Public CompanyRead-shaped view incl. aggregates (None-safe)."""
    if company is None:
        return None
    aggregates = job_aggregates(db).get(company.normalized_name, {})
    return {
        "id": company.id,
        "normalized_name": company.normalized_name,
        "display_name": company.display_name,
        "domain": company.domain,
        "website": company.website,
        "careers_url": company.careers_url,
        "industry": company.industry,
        "company_size": company.company_size,
        "first_seen_job_at": company.first_seen_job_at,
        "last_seen_job_at": company.last_seen_job_at,
        "active_job_count": aggregates.get("active_job_count", 0),
        "distinct_role_count": aggregates.get("distinct_role_count", 0),
        "source_count": aggregates.get("source_count", 0),
    }


def company_view_for_job(db: Session, job: Job) -> dict | None:
    """CompanyRead-shaped view attached to a job detail response."""
    company = find_company(db, job.company)
    return company_view(db, company)


def list_companies(db: Session) -> list[Company]:
    return list(db.scalars(select(Company).order_by(Company.display_name)))


def top_companies(db: Session, limit: int = 5) -> list[dict]:
    """Top employers by observed active-job count."""
    counts = job_aggregates(db)
    ranked = sorted(
        counts.items(),
        key=lambda item: (item[1]["active_job_count"], item[0]),
        reverse=True,
    )
    result = []
    for key, agg in ranked[:limit]:
        company = db.scalar(
            select(Company).where(Company.normalized_name == key).limit(1)
        )
        result.append(
            {
                "id": company.id if company else None,
                "normalized_name": key,
                "display_name": company.display_name if company else key,
                "active_job_count": agg["active_job_count"],
                "distinct_role_count": agg["distinct_role_count"],
                "source_count": agg["source_count"],
            }
        )
    return result
