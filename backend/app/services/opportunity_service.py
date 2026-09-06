"""Opportunity Decision Engine (Phase 5, v1).

Blends the PERSONAL MATCH (how well the job fits) with the Phase 4 job-quality
signals (is this a good listing) into a single OPPORTUNITY SCORE and a final
ACTIONABLE RECOMMENDATION. Cap rules keep unusable listings from ever landing
in a high band, and documented blockers force SKIP regardless of the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config.settings import get_settings
from app.services.freshness_service import STALE
from app.services.matching_service import band_for_score

OPPORTUNITY_VERSION = "v1"

# Cap rules: a qualifying condition lowers the maximum possible score.
_CAP_STALE = 55
_CAP_LOW_QUALITY = 45
_CAP_EMPTY_MATCH = 60


@dataclass
class OpportunityComputation:
    match_score: float | None
    quality_score: int | None
    freshness_score: int | None
    company_score: int | None
    opportunity_score: float
    recommendation: str
    opportunity_version: str
    explanation: list[dict[str, Any]]
    blockers: list[str]
    calculated_at: datetime


def weights() -> dict[str, float]:
    raw = get_settings().opportunity_score_weights or {}
    keys = ("match", "quality", "freshness", "company")
    total = sum(raw.get(k, 0.0) for k in keys)
    if total <= 0:
        return {k: 0.0 for k in keys}
    return {k: raw.get(k, 0.0) / total for k in keys}


def calculate(
    *,
    match_score: float | None,
    quality: Any,
    freshness_raw: str | None = None,
    blockers: list[str] | None = None,
    as_of: datetime | None = None,
) -> OpportunityComputation:
    """Compute the opportunity score from match + quality building blocks."""
    clock = as_of or datetime.now(timezone.utc)
    blockers = list(blockers or [])

    quality_score = getattr(quality, "overall_score", None)
    freshness_score = None
    company_score = None
    if quality is not None:
        freshness_score = quality.components.get("freshness", {}).get("score")
        company_score = quality.components.get("company", {}).get("score")

    weights_map = weights()
    available: dict[str, float] = {}
    for key, value in (
        ("match", match_score),
        ("quality", quality_score),
        ("freshness", freshness_score),
        ("company", company_score),
    ):
        if value is not None and weights_map.get(key):
            available[key] = float(value)

    cap = 100
    if freshness_raw == STALE:
        cap = min(cap, _CAP_STALE)
    if quality_score is not None and quality_score < 30:
        cap = min(cap, _CAP_LOW_QUALITY)
    if match_score is None:
        cap = min(cap, _CAP_EMPTY_MATCH)

    if not available:
        score = 0
    else:
        weight_total = sum(weights_map[k] for k in available)
        raw = sum(v * weights_map[k] for k, v in available.items()) / weight_total
        score = round(min(100.0, max(0.0, raw)))
    score = min(score, cap)

    if blockers:
        recommendation = "SKIP"
    else:
        recommendation = band_for_score(float(score))

    explanation: list[dict[str, Any]] = []
    for key, value in (
        ("match", match_score),
        ("quality", quality_score),
        ("freshness", freshness_score),
        ("company", company_score),
    ):
        explanation.append(
            {
                "key": key,
                "label": _kebab(key),
                "score": value,
                "weight": weights_map.get(key, 0.0),
                "message": _message(key, value),
            }
        )
    caps_applied = []
    if freshness_raw == STALE:
        caps_applied.append(f"Stale posting capped the score at {_CAP_STALE}")
    if quality_score is not None and quality_score < 30:
        caps_applied.append(f"Low listing quality capped the score at {_CAP_LOW_QUALITY}")
    if match_score is None:
        caps_applied.append(f"Match could not be evaluated; capped at {_CAP_EMPTY_MATCH}")
    for cap_note in caps_applied:
        explanation.append(
            {
                "key": "cap",
                "label": "Score cap",
                "score": None,
                "weight": 0.0,
                "message": cap_note,
            }
        )

    return OpportunityComputation(
        match_score=match_score,
        quality_score=quality_score,
        freshness_score=freshness_score,
        company_score=company_score,
        opportunity_score=float(score),
        recommendation=recommendation,
        opportunity_version=OPPORTUNITY_VERSION,
        explanation=explanation,
        blockers=blockers,
        calculated_at=clock,
    )


def _kebab(key: str) -> str:
    return key.replace("_", " ").title()


def _message(key: str, value: float | None) -> str:
    if value is None:
        if key == "match":
            return "Personal match not computed"
        return "Signal not available"
    if key == "match":
        return f"Personal match score {value:.0f}/100"
    if key == "quality":
        return f"Listing quality score {value:.0f}/100"
    if key == "freshness":
        return f"Freshness score {value:.0f}/100"
    return f"Company score {value:.0f}/100"
