"""Deterministic, versioned Job Quality Score (Phase 4, v1).

The overall score is a weighted average of per-signal scores over the signals
that are genuinely available. A missing signal (e.g. no posting date, no
salary) is never turned into a penalty: it is a missing-information signal
with a neutral score and its weight is excluded from the denominator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.company import Company
from app.models.job import Job
from app.models.quality import JobQualityScore
from app.services import freshness_service
from app.services.freshness_service import FreshnessInfo

SCORING_VERSION = "v1"

_DEFAULT_WEIGHTS: dict[str, float] = {
    "freshness": 0.25,
    "description": 0.20,
    "requirements": 0.15,
    "application": 0.15,
    "company": 0.10,
    "location": 0.10,
    "salary": 0.05,
}

LABELS: dict[str, str] = {
    "freshness": "Freshness",
    "description": "Description",
    "requirements": "Requirements",
    "application": "Application",
    "company": "Company",
    "location": "Location",
    "salary": "Salary",
}


def weights() -> dict[str, float]:
    """Effective component weights, normalized to sum to 1.0."""
    raw = get_settings().quality_score_weights or _DEFAULT_WEIGHTS
    total = sum(raw.get(k, 0.0) for k in LABELS)
    if total <= 0:
        return dict(_DEFAULT_WEIGHTS)
    return {k: raw.get(k, 0.0) / total for k in LABELS}


@dataclass
class QualityComputation:
    """Fresh result of a quality evaluation (also the API read shape)."""

    overall_score: int
    scoring_version: str
    components: dict[str, dict[str, Any]]
    positive: list[str]
    negative: list[str]
    calculated_at: datetime


def calculate(
    db: Session,
    job: Job,
    *,
    as_of: datetime | None = None,
    store: bool = True,
    company: Company | None = None,
) -> QualityComputation:
    """Evaluate job quality and (by default) persist the v1 score row."""
    clock = as_of or datetime.now(timezone.utc)
    freshness = freshness_service.classify(job.posted_date, as_of=clock)
    if company is None:
        from app.services import company_service

        company = company_service.find_company(db, job.company)

    components = _component_scores(job, freshness, company)
    messages = _message_scores(job, freshness, company, components)
    overall = _overall(components)

    positive = [
        m["message"]
        for m in messages.values()
        if m["sentiment"] == "positive"
    ]
    negative = [
        m["message"]
        for m in messages.values()
        if m["sentiment"] == "negative"
    ]

    result = QualityComputation(
        overall_score=overall,
        scoring_version=SCORING_VERSION,
        components={
            key: {
                "score": components[key],
                "label": LABELS[key],
                "message": messages[key]["message"],
                "sentiment": messages[key]["sentiment"],
            }
            for key in LABELS
        },
        positive=positive,
        negative=negative,
        calculated_at=clock,
    )

    if store:
        _store(db, job.id, result)
    return result


def _component_scores(
    job: Job, freshness: FreshnessInfo, company: Company | None
) -> dict[str, int | None]:
    return {
        "freshness": freshness.score,
        "description": _description_score(job.description),
        "requirements": _requirements_score(job.requirements),
        "application": _application_score(job),
        "company": _company_score(company),
        "location": _location_score(job.location),
        "salary": _salary_score(job.salary),
    }


def _description_score(text: str | None) -> int:
    if not text:
        return 20
    length = len(text)
    if length < 150:
        return 50
    if length < 400:
        return 80
    return 100


def _requirements_score(items: list[str] | None) -> int:
    count = len(items or [])
    if count == 0:
        return 30
    if count <= 2:
        return 60
    if count <= 5:
        return 80
    return 100


def _application_score(job: Job) -> int:
    application_url = job.application_url or None
    href = job.url or None
    if application_url:
        return 100 if application_url != href else 70
    return 20


def _company_score(company: Company | None) -> int:
    if company is None:
        return 10
    score = 40  # employer identified
    if company.website or company.careers_url:
        score += 25
    if company.domain:
        score += 20
    return min(100, score)


def _location_score(location: str | None) -> int:
    if not location:
        return 20
    return 100 if "," in location else 70


def _salary_score(salary: str | None) -> int:
    # Missing salary is missing information, not a bad-quality signal.
    return 100 if salary else 40


def _message_scores(
    job: Job,
    freshness: FreshnessInfo,
    company: Company | None,
    components: dict[str, int | None],
) -> dict[str, dict[str, str]]:
    messages: dict[str, dict[str, str]] = {}

    if freshness.score is None:
        messages["freshness"] = {
            "score": None,
            "message": "Posting date unknown",
            "sentiment": "info",
        }
    else:
        messages["freshness"] = {
            "score": freshness.score,
            "message": freshness.explanation,
            "sentiment": "positive",
        }

    desc = components["description"]
    if desc == 20:
        messages["description"] = {
            "score": 20,
            "message": "No job description",
            "sentiment": "negative",
        }
    elif desc >= 80:
        messages["description"] = {
            "score": desc,
            "message": "Detailed job description",
            "sentiment": "positive",
        }
    else:
        messages["description"] = {
            "score": desc,
            "message": "Brief job description",
            "sentiment": "info",
        }

    req = components["requirements"]
    if req == 30:
        messages["requirements"] = {
            "score": 30,
            "message": "Requirements not listed",
            "sentiment": "negative",
        }
    elif req >= 80:
        messages["requirements"] = {
            "score": req,
            "message": "Requirements clearly listed",
            "sentiment": "positive",
        }
    else:
        messages["requirements"] = {
            "score": req,
            "message": "A few requirements listed",
            "sentiment": "info",
        }

    app_score = components["application"]
    if app_score == 100:
        messages["application"] = {
            "score": 100,
            "message": "Direct application link",
            "sentiment": "positive",
        }
    elif app_score >= 70:
        messages["application"] = {
            "score": app_score,
            "message": "Application link available",
            "sentiment": "info",
        }
    else:
        messages["application"] = {
            "score": 20,
            "message": "No application link",
            "sentiment": "negative",
        }

    comp = components["company"]
    if company is None:
        messages["company"] = {
            "score": 10,
            "message": "Employer not identified",
            "sentiment": "negative",
        }
    elif company.domain or company.website:
        messages["company"] = {
            "score": comp,
            "message": "Employer identified with a website",
            "sentiment": "positive",
        }
    else:
        messages["company"] = {
            "score": comp,
            "message": "Employer identified",
            "sentiment": "info",
        }

    loc = components["location"]
    if loc == 20:
        messages["location"] = {
            "score": 20,
            "message": "Location not specified",
            "sentiment": "info",
        }
    elif loc >= 100:
        messages["location"] = {
            "score": 100,
            "message": "Precise location provided",
            "sentiment": "positive",
        }
    else:
        messages["location"] = {
            "score": loc,
            "message": "Location provided",
            "sentiment": "info",
        }

    if components["salary"] == 100:
        messages["salary"] = {
            "score": 100,
            "message": "Salary listed",
            "sentiment": "positive",
        }
    else:
        messages["salary"] = {
            "score": 40,
            "message": "Salary not listed",
            "sentiment": "info",
        }

    return messages


def _overall(components: dict[str, int | None]) -> int:
    """Weighted average over available signals; unknown signals excluded."""
    weights_map = weights()
    numerator = 0.0
    denominator = 0.0
    for key in LABELS:
        score = components.get(key)
        if score is None:
            continue
        numerator += float(score) * weights_map[key]
        denominator += weights_map[key]
    if denominator <= 0:
        return 0
    return round(min(100.0, max(0.0, numerator / denominator)))


def _store(db: Session, job_id: int, result: QualityComputation) -> None:
    row = db.scalar(
        select(JobQualityScore).where(
            JobQualityScore.job_id == job_id,
            JobQualityScore.scoring_version == result.scoring_version,
        )
    )
    if row is None:
        row = JobQualityScore(
            job_id=job_id,
            scoring_version=result.scoring_version,
        )
        db.add(row)

    row.freshness_score = result.components["freshness"]["score"]
    row.description_score = result.components["description"]["score"]
    row.requirements_score = result.components["requirements"]["score"]
    row.application_score = result.components["application"]["score"]
    row.company_score = result.components["company"]["score"]
    row.location_score = result.components["location"]["score"]
    row.salary_score = result.components["salary"]["score"]
    row.overall_score = result.overall_score
    row.explanation = [
        {
            "label": result.components[key]["label"],
            "score": result.components[key]["score"],
            "message": result.components[key]["message"],
            "sentiment": result.components[key]["sentiment"],
        }
        for key in LABELS
    ]
    row.calculated_at = result.calculated_at
    db.flush()


def recalculate_all(db: Session, *, as_of: datetime | None = None) -> int:
    """Recompute and store v1 scores for every job in the database."""
    jobs = list(db.scalars(select(Job).order_by(Job.id)))
    for job in jobs:
        calculate(db, job, as_of=as_of, store=True)
    return len(jobs)


def from_row(row: JobQualityScore | None) -> QualityComputation | None:
    """Reconstruct an API read shape from a stored score row."""
    if row is None:
        return None
    components = {
        key: {
            "score": row_explanation_or_score(row, key),
            "label": LABELS[key],
            "message": _explanation_message(row, key),
            "sentiment": _explanation_sentiment(row, key),
        }
        for key in LABELS
    }
    positive = [
        entry["message"]
        for entry in row.explanation or []
        if entry.get("sentiment") == "positive"
    ]
    negative = [
        entry["message"]
        for entry in row.explanation or []
        if entry.get("sentiment") == "negative"
    ]
    return QualityComputation(
        overall_score=row.overall_score,
        scoring_version=row.scoring_version,
        components=components,
        positive=positive,
        negative=negative,
        calculated_at=row.calculated_at,
    )


def _row_explanation(row: JobQualityScore, key: str) -> dict | None:
    for entry in row.explanation or []:
        if entry.get("label") == LABELS[key]:
            return entry
    return None


def row_explanation_or_score(row: JobQualityScore, key: str) -> int | None:
    entry = _row_explanation(row, key)
    if entry is not None:
        return entry.get("score")
    return getattr(row, f"{key}_score", None)


def _explanation_message(row: JobQualityScore, key: str) -> str:
    entry = _row_explanation(row, key)
    return entry.get("message", "") if entry else ""


def _explanation_sentiment(row: JobQualityScore, key: str) -> str:
    entry = _row_explanation(row, key)
    return entry.get("sentiment", "info") if entry else "info"
