"""Deterministic posting-freshness classification (Phase 4).

Freshness is a pure, deterministic function of the employer's posting date.
``UNKNOWN`` means we have no reliable posting date and yields a ``score`` of
``None`` — freshness is never invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

VERY_FRESH = "VERY_FRESH"
FRESH = "FRESH"
RECENT = "RECENT"
AGING = "AGING"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

# Status -> (inclusive min_days, inclusive max_days). None max = unbounded.
AGE_RANGES: dict[str, tuple[int | None, int | None]] = {
    VERY_FRESH: (0, 3),   # 0-3 days
    FRESH: (4, 7),        # 4-7 days
    RECENT: (8, 14),      # 8-14 days
    AGING: (15, 30),      # 15-30 days
    STALE: (31, None),    # 31+ days
}

# Status -> 0-100 score (UNKNOWN has no score: freshness is never invented).
SCORES: dict[str, int | None] = {
    VERY_FRESH: 100,
    FRESH: 90,
    RECENT: 75,
    AGING: 50,
    STALE: 20,
    UNKNOWN: None,
}

# Newest -> oldest, used for human-readable ordering in the UI.
FRESHNESS_RANK = {
    VERY_FRESH: 5,
    FRESH: 4,
    RECENT: 3,
    AGING: 2,
    STALE: 1,
    UNKNOWN: 0,
}

_status_label = {
    VERY_FRESH: "very fresh",
    FRESH: "fresh",
    RECENT: "recent",
    AGING: "aging",
    STALE: "stale",
}


@dataclass(frozen=True)
class FreshnessInfo:
    """Classification of one posting date."""

    status: str
    age_in_days: int | None
    score: int | None
    as_of: datetime
    explanation: str


def age_in_days(posted: date | None, as_of: date | None = None) -> int | None:
    """Age of a posting in whole days. Future postings clamp to 0."""
    if posted is None:
        return None
    reference = as_of or date.today()
    return max(0, (reference - posted).days)


def classify(posted: date | None, as_of: datetime | None = None) -> FreshnessInfo:
    """Classify a posting date into a status, age, and 0-100 score.

    ``as_of`` defaults to the current UTC time so tests can pin the clock.
    """
    clock = as_of or datetime.now(timezone.utc)
    today = clock.date()
    age = age_in_days(posted, today)

    if age is None:
        return FreshnessInfo(
            status=UNKNOWN,
            age_in_days=None,
            score=None,
            as_of=clock,
            explanation="Posting date unknown",
        )

    for band_status, (min_age, max_age) in AGE_RANGES.items():
        if min_age <= age and (max_age is None or age <= max_age):
            label = _status_label[band_status]
            day_word = "day" if age == 1 else "days"
            return FreshnessInfo(
                status=band_status,
                age_in_days=age,
                score=SCORES[band_status],
                as_of=clock,
                explanation=f"Posted {age} {day_word} ago — {label}",
            )

    # Unreachable given the covering bands, but keep the return typed.
    return FreshnessInfo(
        status=STALE,
        age_in_days=age,
        score=SCORES[STALE],
        as_of=clock,
        explanation=f"Posted {age} days ago — stale",
    )


def age_range(freshness: str) -> tuple[int | None, int | None] | None:
    """Inclusive (min_days, max_days) age window for a status.

    Returns ``None`` for ``UNKNOWN``, which the caller maps to ``posted_date
    IS NULL``.
    """
    status = (freshness or "").upper()
    if status == UNKNOWN:
        return None
    if status not in AGE_RANGES:
        raise ValueError(f"Unknown freshness status: {freshness}")
    return AGE_RANGES[status]


def freshness_filter(
    freshness: str,
    posted_column,
    as_of: date,
):
    """SQLAlchemy conditions on ``posted_column`` for the given status.

    Returns ``None`` for UNKNOWN (caller applies ``posted_date IS NULL``),
    otherwise a list of inclusive age-window conditions.
    """
    window = age_range(freshness)
    if window is None:
        return None

    lo, hi = window
    today = as_of
    conditions = []
    if hi is not None:
        conditions.append(posted_column >= today - timedelta(days=hi))
    if lo is not None:
        conditions.append(posted_column <= today - timedelta(days=lo))
    return conditions
