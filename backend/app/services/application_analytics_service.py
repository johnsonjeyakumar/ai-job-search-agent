"""Deterministic application analytics (Phase 8, no LLM anywhere).

All figures are computed from tracked application history (events + legacy
fallback fields). Formulas use explicit denominators and return ``None`` for a
rate whenever the denominator is zero — never a misleading 0%.

Date-range basis (documented, never mixed silently):
    Funnel stages are bucketed by the FIRST ``event_timestamp.date()`` at which
    the application reached that stage (e.g. SUBMITTED) within the range.
    Legacy rows without events fall back to ``created_at`` (discovery /
    DISCOVERED) and ``applied_date`` (submissions beyond applied).
    ``all`` ignores timestamps entirely.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.application_tracking import status as app_status
from app.application_tracking.status import FUNNEL_STEPS
from app.models.application import Application, FollowUp
from app.models.application_tracking import (
    SMALL_SAMPLE_THRESHOLD,
    ApplicationEvent,
)
from app.models.job import Job
from app.services import application_lifecycle_service as lifecycle
from app.services import company_service
from app.services.application_lifecycle_service import follow_up_state

# Milestone event types per funnel stage (first-reach semantics).
_MILESTONE_EVENTS = {
    "DISCOVERED": "APPLICATION_CREATED",
    "SHORTLISTED": "SHORTLISTED",
    "PREPARING": "PACKAGE_PREPARED",
    "READY_FOR_REVIEW": "PACKAGE_READY_FOR_REVIEW",
    "APPROVED": "APPROVED",
    "SUBMITTED": "SUBMITTED",
    "SUBMISSION_CONFIRMED": "SUBMISSION_CONFIRMED",
    "RESPONSE_RECEIVED": "RESPONSE_RECEIVED",
    "INTERVIEW": "INTERVIEW_SCHEDULED",
    "OFFER": "OFFER_RECEIVED",
    "REJECTED": "REJECTED",
    "WITHDRAWN": "WITHDRAWN",
}

# Funnel milestone history types queried for a whole cohort.
_EVENT_AHEAD_MILESTONES = {
    "SHORTLISTED",
    "PACKAGE_PREPARED",
    "PACKAGE_READY_FOR_REVIEW",
    "APPROVED",
    "SUBMITTED",
    "SUBMISSION_CONFIRMED",
    "RESPONSE_RECEIVED",
    "INTERVIEW_SCHEDULED",
    "OFFER_RECEIVED",
    "REJECTED",
    "WITHDRAWN",
}

# Stages that count as "the company responded" (post-submission engagement).
_RESPONSE_STAGES = frozenset({"RESPONSE_RECEIVED", "INTERVIEW", "OFFER"})

RATE_DENOMINATOR_LABELS = {
    "shortlist_rate": "shortlisted / discovered",
    "application_rate": "submitted / discovered",
    "submission_confirmed_rate": "submission_confirmed / submitted",
    "response_rate": "responses / submitted",
    "interview_rate": "interviews / submitted",
    "offer_rate": "offers / submitted",
    "rejection_rate": "rejected / submitted",
    "withdrawal_rate": "withdrawn / submitted",
}

DATE_RANGE_OPTIONS = (
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_year",
    "all",
    "custom",
)


@dataclass
class DateRange:
    label: str
    start: date | None
    end: date | None
    basis: str

    def contains(self, when: datetime | date | None) -> bool:
        if when is None:
            return False
        day = when.date() if isinstance(when, datetime) else when
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day > self.end:
            return False
        return True


def _today() -> date:
    return datetime.now().date()


def resolve_date_range(
    range_name: str = "all",
    *,
    start: str | None = None,
    end: str | None = None,
) -> DateRange:
    """Normalize a range option into an inclusive [start, end] date window.

    ``range_name`` takes precedence; ``custom`` requires ``start``/``end``
    (falls back to all-time when either is missing). Basis text documents what
    the filter is applied to.
    """
    today = _today()
    if range_name == "last_7_days":
        basis = "events event_timestamp.date()/created_at in the last 7 calendar days (inclusive)"
        return DateRange("last_7_days", today - timedelta(days=6), today, basis)
    if range_name == "last_30_days":
        basis = "events event_timestamp.date()/created_at in the last 30 calendar days (inclusive)"
        return DateRange("last_30_days", today - timedelta(days=29), today, basis)
    if range_name == "last_90_days":
        basis = "events event_timestamp.date()/created_at in the last 90 calendar days (inclusive)"
        return DateRange("last_90_days", today - timedelta(days=89), today, basis)
    if range_name == "this_year":
        basis = "events event_timestamp.date()/created_at since Jan 1 of the current year"
        return DateRange("this_year", date(today.year, 1, 1), today, basis)
    if range_name == "custom":
        try:
            start_date = date.fromisoformat(start) if start else None
            end_date = date.fromisoformat(end) if end else None
        except ValueError as exc:
            raise ValueError(
                "Custom date range requires start/end as YYYY-MM-DD."
            ) from exc
        return DateRange("custom", start_date, end_date,
                         "custom event_timestamp.date()/created_at window (inclusive)")
    return DateRange("all", None, None,
                     "all time — no timestamp filtering")


# ---------------------------------------------------------------------------
# Per-cohort milestone map
# ---------------------------------------------------------------------------


def _applications(db: Session) -> list[Application]:
    return list(db.scalars(select(Application).order_by(Application.id)))


def _milestone_dates(db: Session, apps: list[Application]) -> dict[int, dict[str, date]]:
    """app_id -> {milestone_stage: first-reach date} for every application.

    Builds the map from immutable events in one query, then fills legacy rows
    (no events) from their recorded fields so pre-Phase-8 data still counts.
    """
    ids = [a.id for a in apps]
    out: dict[int, dict[str, date]] = {a.id: {} for a in apps}
    if ids:
        rows = db.execute(
            select(
                ApplicationEvent.application_id,
                ApplicationEvent.event_type,
                func.min(ApplicationEvent.event_timestamp),
            )
            .where(ApplicationEvent.application_id.in_(ids))
            .where(
                ApplicationEvent.event_type.in_(
                    list(_EVENT_AHEAD_MILESTONES) + ["APPLICATION_CREATED"]
                )
            )
            .group_by(ApplicationEvent.application_id, ApplicationEvent.event_type)
        ).all()
        reverse = {}
        for stage, event_type in _MILESTONE_EVENTS.items():
            reverse.setdefault(event_type, stage)
        for application_id, event_type, ts in rows:
            stage = reverse.get(event_type)
            if stage is None:
                continue
            day = ts.date()
            current = out[application_id].get(stage)
            if current is None or day < current:
                out[application_id][stage] = day

    # Legacy fallback (no events and older lifecycle rows).
    for app in apps:
        reached = out[app.id]
        if "DISCOVERED" not in reached and app.created_at is not None:
            reached["DISCOVERED"] = app.created_at.date()
        sub = reached.get("SUBMITTED") or reached.get("SUBMISSION_CONFIRMED")
        if (
            sub is None
            and app.lifecycle_status
            in app_status.SUBMITTED_STATUSES | {"SUBMITTED", "SUBMISSION_CONFIRMED"}
        ):
            base = app.applied_date or (app.created_at.date() if app.created_at else None)
            if base is not None:
                reached["SUBMITTED"] = base
        if (
            reached.get("SUBMISSION_CONFIRMED") is None
            and app.lifecycle_status == "SUBMISSION_CONFIRMED"
        ):
            if app.applied_date is not None:
                reached["SUBMISSION_CONFIRMED"] = app.applied_date
    return out


def _in_range_counts(
    milestones: dict[int, dict[str, date]], window: DateRange
) -> dict[str, set[int]]:
    """App ids that first reached each funnel stage within the window."""
    counted: dict[str, set[int]] = {stage: set() for stage in FUNNEL_STEPS}
    for app_id, reached in milestones.items():
        for stage in FUNNEL_STEPS:
            when = reached.get(stage)
            if when is not None and window.contains(when):
                counted[stage].add(app_id)
    return counted


# ---------------------------------------------------------------------------
# Funnel
# ---------------------------------------------------------------------------


def funnel(
    db: Session,
    range_name: str = "all",
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Funnel counts + documented conversion rates.

    Discovered is the number of jobs discovered in the window (jobs table);
    the remaining stages count tracked applications that first reached each
    stage inside the window. Counts are cumulative per stage.
    """
    window = resolve_date_range(range_name, start=start, end=end)
    apps = _applications(db)
    milestones = _milestone_dates(db, apps)
    counted = _in_range_counts(milestones, window)

    total_jobs = db.scalar(select(func.count(Job.id))) or 0
    jobs_in_range = 0
    if window.start is not None or window.end is not None:
        rows = db.scalars(select(Job.discovered_date)).all()
        jobs_in_range = sum(1 for ts in rows if window.contains(ts))
    discovered = (
        total_jobs if window.label == "all" else jobs_in_range
    )

    def union(*stages: str) -> int:
        # Later stages imply earlier ones; count distinct apps that reached at
        # least one of the given stages (i.e., the stage itself in our first-
        # reach model).
        return len(set().union(*(counted[s] for s in stages)))

    steps = {
        "DISCOVERED": discovered,
        "SHORTLISTED": union("SHORTLISTED"),
        "PREPARING": union("PREPARING"),
        "READY_FOR_REVIEW": union("READY_FOR_REVIEW"),
        "APPROVED": union("APPROVED"),
        "SUBMITTED": union("SUBMITTED", "SUBMISSION_CONFIRMED"),
        "SUBMISSION_CONFIRMED": union("SUBMISSION_CONFIRMED"),
        "RESPONSE_RECEIVED": union(
            "RESPONSE_RECEIVED", "INTERVIEW", "OFFER"
        ),
        "INTERVIEW": union("INTERVIEW"),
        "OFFER": union("OFFER"),
        "REJECTED": union("REJECTED"),
        "WITHDRAWN": union("WITHDRAWN"),
    }

    submitted = steps["SUBMITTED"]
    rates = {
        "shortlist_rate": _pct(steps["SHORTLISTED"], discovered),
        "application_rate": _pct(submitted, discovered),
        "submission_confirmed_rate": _pct(steps["SUBMISSION_CONFIRMED"], submitted),
        "response_rate": _pct(steps["RESPONSE_RECEIVED"], submitted),
        "interview_rate": _pct(steps["INTERVIEW"], submitted),
        "offer_rate": _pct(steps["OFFER"], submitted),
        "rejection_rate": _pct(steps["REJECTED"], submitted),
        "withdrawal_rate": _pct(steps["WITHDRAWN"], submitted),
    }
    return {
        "range": window.label,
        "start": window.start.isoformat() if window.start else None,
        "end": window.end.isoformat() if window.end else None,
        "date_basis": window.basis,
        "steps": [
            {"step": stage, "label": stage.replace("_", " ").title(), "count": steps[stage]}
            for stage in FUNNEL_STEPS
        ],
        "rates": rates,
        "rate_formulas": RATE_DENOMINATOR_LABELS,
        "small_sample_threshold": SMALL_SAMPLE_THRESHOLD,
    }


def _pct(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((part / total) * 100, 1)


def status_counts(
    db: Session,
    range_name: str = "all",
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Current lifecycle distribution (real numbers, not funnel buckets)."""
    window = resolve_date_range(range_name, start=start, end=end)
    apps = _applications(db)
    counts: dict[str, int] = {}
    for status_value in app_status.TRACKING_STATUSES:
        counts[status_value] = sum(1 for a in apps if a.lifecycle_status == status_value)
    total = len(apps)
    return {
        "range": window.label,
        "start": window.start.isoformat() if window.start else None,
        "end": window.end.isoformat() if window.end else None,
        "date_basis": window.basis,
        "status_counts": counts,
        "total_tracked": total,
    }


def over_time(
    db: Session,
    range_name: str = "all",
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Simple weekly trends: applications / responses / interviews per ISO week.

    No predictive analytics and no ML (Phase 8 item 35).
    """
    window = resolve_date_range(range_name, start=start, end=end)
    apps = _applications(db)
    milestones = _milestone_dates(db, apps)

    weekly: dict[tuple[int, int], dict[str, int]] = {}
    for app in apps:
        created = (
            app.created_at.date() if app.created_at is not None else None
        )
        if created is not None and window.contains(created):
            key = (created.isocalendar()[0], created.isocalendar()[1])
            weekly.setdefault(key, {"applications": 0, "responses": 0, "interviews": 0})
            weekly[key]["applications"] += 1
        for stage, counter in (
            ("RESPONSE_RECEIVED", "responses"),
            ("INTERVIEW", "interviews"),
        ):
            when = milestones.get(app.id, {}).get(stage, None)
            if when is not None and window.contains(when):
                key = (when.isocalendar()[0], when.isocalendar()[1])
                weekly.setdefault(key, {"applications": 0, "responses": 0, "interviews": 0})
                weekly[key][counter] += 1
    items = [
        {
            "year": year,
            "week": week,
            "week_start": _week_start(year, week).isoformat(),
            **counts,
        }
        for (year, week), counts in sorted(weekly.items())
    ]
    return items


def _week_start(year: int, week: int) -> date:
    first = date(year, 1, 1)
    # Monday-based ISO week 1 handling
    weekday = first.weekday()
    week1_monday = (
        first - timedelta(days=weekday)
        if weekday <= 3
        else first + timedelta(days=7 - weekday)
    )
    return week1_monday + timedelta(weeks=week - 1)


# ---------------------------------------------------------------------------
# Time to response / interview / offer
# ---------------------------------------------------------------------------


def response_times(db: Session) -> dict:
    """days_to_response / days_to_interview / days_to_offer (when dates exist).

    Never invents missing dates: only applications with both a submission date
    and the relevant outcome date are measured.
    """
    apps = _applications(db)
    milestones = _milestone_dates(db, apps)

    def measure(stage_events: tuple[str, ...]) -> list[int]:
        days: list[int] = []
        for app in apps:
            sub = app.applied_date or (app.created_at.date() if app.created_at else None)
            out = None
            for stage in stage_events:
                d = milestones.get(app.id, {}).get(stage)
                if d is not None:
                    out = d if out is None else min(out, d)
            if sub is not None and out is not None and out >= sub:
                days.append((out - sub).days)
        return days

    return {
        "days_to_response": _stat(measure(("RESPONSE_RECEIVED", "INTERVIEW", "OFFER"))),
        "days_to_interview": _stat(measure(("INTERVIEW",))),
        "days_to_offer": _stat(measure(("OFFER",))),
    }


def _stat(days: list[int]) -> dict:
    if not days:
        return {"measured": 0, "average_days": None, "median_days": None}
    ordered = sorted(days)
    mid = len(ordered) // 2
    median = (
        ordered[mid]
        if len(ordered) % 2
        else (ordered[mid - 1] + ordered[mid]) / 2
    )
    return {
        "measured": len(days),
        "average_days": round(sum(days) / len(days), 1),
        "median_days": median,
    }


# ---------------------------------------------------------------------------
# Dimension performance (roles / locations / companies / sources / resumes)
# ---------------------------------------------------------------------------


def _performance_rows(
    db: Session,
    *,
    key_fn,
    label_fn=None,
    apps: list[Application] | None = None,
) -> list[dict]:
    if apps is None:
        apps = _applications(db)
    milestones = _milestone_dates(db, apps)
    grouped: dict = {}
    order: list = []
    for app in apps:
        job = db.get(Job, app.job_id)
        key = key_fn(app, job)
        group_label = label_fn(app, job) if label_fn else key
        if key is None:
            key = "unknown"
            group_label = group_label or "Unknown"
        if key not in grouped:
            grouped[key] = {
                "key": key,
                "label": group_label,
                "applications": 0,
                "responses": 0,
                "interviews": 0,
                "offers": 0,
                "rejections": 0,
                "submitted": 0,
            }
            order.append(key)
        g = grouped[key]
        g["applications"] += 1
        reached = milestones.get(app.id, {})
        # Only outcomes backed by a real milestone (or legacy fallback
        # submission) are counted; nothing is ever invented.
        if any(s in reached for s in ("SUBMITTED", "SUBMISSION_CONFIRMED")):
            g["submitted"] += 1
        if any(s in reached for s in ("RESPONSE_RECEIVED", "INTERVIEW", "OFFER")):
            g["responses"] += 1
        if "INTERVIEW" in reached:
            g["interviews"] += 1
        if "OFFER" in reached:
            g["offers"] += 1
        if "REJECTED" in reached:
            g["rejections"] += 1

    rows = []
    for key in order:
        g = grouped[key]
        rows.append(
            {
                **g,
                "response_rate": _pct(g["responses"], g["submitted"]),
                "interview_rate": _pct(g["interviews"], g["submitted"]),
                "offer_rate": _pct(g["offers"], g["submitted"]),
                "rejection_rate": _pct(g["rejections"], g["submitted"]),
                "sample_size": g["submitted"],
                "limited_data": g["submitted"] < SMALL_SAMPLE_THRESHOLD,
                "limited_label": f"Limited sample (n={g['submitted']})"
                if g["submitted"] < SMALL_SAMPLE_THRESHOLD
                else None,
            }
        )
    rows.sort(key=lambda r: r["submitted"], reverse=True)
    return rows


def by_role(db: Session) -> list[dict]:
    return _performance_rows(
        db,
        key_fn=lambda app, job: (job.title if job else None),
        label_fn=lambda app, job: (job.title if job else None) or "Unknown role",
    )


def by_location(db: Session) -> list[dict]:
    return _performance_rows(
        db,
        key_fn=lambda app, job: (job.location if job else None),
        label_fn=lambda app, job: (job.location if job else None) or "Unknown location",
    )


def by_company(db: Session) -> list[dict]:
    def key_fn(app, job):
        if job is None or not job.company:
            return None
        return company_service.normalize_company_name(job.company)

    def label_fn(app, job):
        if job is None:
            return "Unknown"
        return company_service.display_name_for(job.company) or job.company

    return _performance_rows(db, key_fn=key_fn, label_fn=label_fn)


def by_source(db: Session) -> list[dict]:
    return _performance_rows(
        db,
        key_fn=lambda app, job: (job.source if job else None),
        label_fn=lambda app, job: (job.source if job else None) or "unknown",
    )


def by_application_source(db: Session) -> list[dict]:
    """Performance grouped by where the application was actually submitted.

    ``application_source`` is only set from a real recorded submission platform
    (never fabricated); apps without one group as "No submission source".
    """
    return _performance_rows(
        db,
        key_fn=lambda app, job: app.application_source,
        label_fn=lambda app, job: app.application_source or "No submission source",
    )


# ---------------------------------------------------------------------------
# Source intelligence (Phase 9): discovery + submission sources & quality
# ---------------------------------------------------------------------------

# Explicit, documented quality weights (sum to 1.0). Every component is a
# verified rate with a real denominator; never LLM-derived.
SOURCE_QUALITY_WEIGHTS = {
    "submission_rate": 0.15,  # submitted / tracked applications from this source
    "response_rate": 0.40,    # responses / submitted
    "interview_rate": 0.30,   # interviews / submitted
    "offer_rate": 0.15,       # offers / submitted
}

SOURCE_QUALITY_LABELS = {
    "EXCELLENT SIGNAL",
    "GOOD",
    "PROMISING",
    "LIMITED DATA",
    "WEAK SIGNAL",
    "INSUFFICIENT DATA",
}


def _source_quality(row: dict) -> dict:
    """Deterministic 0-100 quality score + explicit band label for a source row.

    Insufficient when nothing was submitted; ``LIMITED DATA`` whenever the
    submitted sample is below the small-sample threshold (score still shown for
    transparency). The ``basis`` field documents exactly what was used.
    """
    submitted = int(row.get("submitted") or 0)
    if submitted == 0:
        return {
            "score": None,
            "label": "INSUFFICIENT DATA",
            "weighted_components": {},
            "basis": SOURCE_QUALITY_BASIS,
        }
    components = {
        "submission_rate": _pct(submitted, int(row.get("applications") or 0)),
        "response_rate": row.get("response_rate"),
        "interview_rate": row.get("interview_rate"),
        "offer_rate": row.get("offer_rate"),
    }
    score = round(
        sum(
            (components[key] or 0.0) * weight
            for key, weight in SOURCE_QUALITY_WEIGHTS.items()
        ),
        1,
    )
    if submitted < SMALL_SAMPLE_THRESHOLD:
        label = "LIMITED DATA"
    elif score >= 70:
        label = "EXCELLENT SIGNAL"
    elif score >= 50:
        label = "GOOD"
    elif score >= 35:
        label = "PROMISING"
    else:
        label = "WEAK SIGNAL"
    return {
        "score": score,
        "label": label,
        "weighted_components": components,
        "basis": SOURCE_QUALITY_BASIS,
    }


SOURCE_QUALITY_BASIS = (
    "score = 0.15*submission_rate (submitted/tracked) + "
    "0.40*response_rate + 0.30*interview_rate + 0.15*offer_rate "
    "(rates over submitted)."
)


def source_performance(db: Session) -> dict:
    """Discovery vs submission sources, each with a deterministic quality score."""
    discovery = by_source(db)
    submission = by_application_source(db)
    return {
        "quality_basis": SOURCE_QUALITY_BASIS,
        "quality_weights": dict(SOURCE_QUALITY_WEIGHTS),
        "small_sample_threshold": SMALL_SAMPLE_THRESHOLD,
        "discovery": [
            {**row, **{"source_quality": _source_quality(row)}}
            for row in discovery
        ],
        "submission": [
            {**row, **{"source_quality": _source_quality(row)}}
            for row in submission
        ],
    }


def by_resume(db: Session) -> list[dict]:
    def key_fn(app, job):
        if app.resume_id is None and not app.resume_name:
            return None
        return app.resume_name or f"resume-{app.resume_id}"

    def label_fn(app, job):
        if app.resume_id is None and not app.resume_name:
            return "No resume"
        name = app.resume_name or f"Resume #{app.resume_id}"
        version = f" · {app.resume_version}" if app.resume_version else ""
        return f"{name}{version}"

    return _performance_rows(db, key_fn=key_fn, label_fn=label_fn)


# ---------------------------------------------------------------------------
# Resume intelligence (Phase 9)
# ---------------------------------------------------------------------------

RESUME_RANK_LABELS = ("STRONGER SIGNAL", "PROMISING", "LIMITED DATA", "INSUFFICIENT DATA")


def _resume_rank(row: dict) -> dict:
    """Deterministic resume rank inferred strictly from verified rates.

    composite = interview_rate + offer_rate (0-200). Below the small-sample
    threshold the label is always LIMITED DATA (score still shown for
    transparency). Nothing here is AI-generated.
    """
    submitted = int(row.get("submitted") or 0)
    composite = round(
        (row.get("interview_rate") or 0.0) + (row.get("offer_rate") or 0.0), 1
    )
    if submitted == 0:
        return {"composite_score": composite, "rank_label": "INSUFFICIENT DATA"}
    if submitted < SMALL_SAMPLE_THRESHOLD:
        return {"composite_score": composite, "rank_label": "LIMITED DATA"}
    if composite >= 150:
        return {"composite_score": composite, "rank_label": "STRONGER SIGNAL"}
    if composite >= 100:
        return {"composite_score": composite, "rank_label": "PROMISING"}
    return {"composite_score": composite, "rank_label": "LIMITED DATA"}


def _filter_apps(
    db: Session,
    *,
    role: str | None = None,
    location: str | None = None,
    source: str | None = None,
    company: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[Application]:
    apps: list[Application] = []
    for app in _applications(db):
        job = db.get(Job, app.job_id)
        job_title = job.title if job else None
        job_company = job.company if job else None
        job_location = job.location if job else None
        job_source = job.source if job else None
        if role and not _contains_any((job_title or ""), role):
            continue
        if location and not _contains_any((job_location or ""), location):
            continue
        if source and job_source != source:
            continue
        if company and not _contains_any((job_company or ""), company):
            continue
        if from_date or to_date:
            when = app.applied_date or (app.created_at.date() if app.created_at else None)
            if when is not None:
                if from_date and when < date.fromisoformat(from_date):
                    continue
                if to_date and when > date.fromisoformat(to_date):
                    continue
        apps.append(app)
    return apps


def resume_performance(
    db: Session,
    *,
    role: str | None = None,
    location: str | None = None,
    source: str | None = None,
    company: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict]:
    """Resume performance (historical snapshots kept), optionally filtered by
    target role / location / discovery source / company / date window.

    Each row carries verified rates plus a derived, deterministic rank label.
    """
    apps = _filter_apps(
        db,
        role=role,
        location=location,
        source=source,
        company=company,
        from_date=from_date,
        to_date=to_date,
    )

    def key_fn(app, job):
        if app.resume_id is None and not app.resume_name:
            return None
        return app.resume_name or f"resume-{app.resume_id}"

    def label_fn(app, job):
        if app.resume_id is None and not app.resume_name:
            return "No resume"
        name = app.resume_name or f"Resume #{app.resume_id}"
        version = f" · {app.resume_version}" if app.resume_version else ""
        return f"{name}{version}"

    rows = []
    for row in _performance_rows(db, key_fn=key_fn, label_fn=label_fn, apps=apps):
        ranked = _resume_rank(row)
        rows.append(
            {
                **row,
                "composite_score": ranked["composite_score"],
                "rank_label": ranked["rank_label"],
            }
        )
    rows.sort(
        key=lambda r: (r.get("composite_score") or -1.0), reverse=True
    )
    return rows


def recommended_resume(
    db: Session,
    *,
    role: str | None = None,
    location: str | None = None,
    source: str | None = None,
) -> dict:
    """Deterministic resume recommendation for a target role / location / source.

    Chooses the highest-composite resume with a qualified sample (at least
    ``SMALL_SAMPLE_THRESHOLD`` submissions). No qualified data yields a plain
    "not enough historical data" answer — never a fabricated pick.
    """
    rows = resume_performance(db, role=role, location=location, source=source)
    candidates = [
        {
            "key": r["key"],
            "label": r["label"],
            "applications": r["applications"],
            "submitted": r["submitted"],
            "responses": r["responses"],
            "interviews": r["interviews"],
            "offers": r["offers"],
            "response_rate": r["response_rate"],
            "interview_rate": r["interview_rate"],
            "offer_rate": r["offer_rate"],
            "composite_score": r["composite_score"],
            "rank_label": r["rank_label"],
        }
        for r in rows
        if r["submitted"] > 0 and r["label"] != "No resume"
    ]
    candidates.sort(
        key=lambda c: (c["composite_score"], c["submitted"]), reverse=True
    )
    qualified = [c for c in candidates if c["submitted"] >= SMALL_SAMPLE_THRESHOLD]
    full_qualified = [
        c for c in qualified if c["rank_label"] in ("STRONGER SIGNAL", "PROMISING")
    ]
    pool = full_qualified or qualified
    winner = pool[0] if pool else None
    alternative = pool[1] if len(pool) > 1 else None
    if winner is None:
        return {
            "role": role,
            "location": location,
            "source": source,
            "candidate": None,
            "alternative": None,
            "recommended_resume_id": None,
            "message": "Not enough historical data to recommend a resume.",
            "candidates": candidates,
            "basis": (
                "Composite = interview_rate + offer_rate over submissions with "
                f"n >= {SMALL_SAMPLE_THRESHOLD}."
            ),
        }
    return {
        "role": role,
        "location": location,
        "source": source,
        "candidate": winner,
        "alternative": alternative,
        "recommended_resume_id": winner["key"],
        "message": None,
        "candidates": candidates,
        "basis": (
            "Composite = interview_rate + offer_rate over submissions with "
            f"n >= {SMALL_SAMPLE_THRESHOLD}."
        ),
    }


# ---------------------------------------------------------------------------
# Follow-up summary (app tracking widgets)
# ---------------------------------------------------------------------------


def follow_up_summary(db: Session) -> dict:
    today = _today()
    follow_ups = list(db.scalars(select(FollowUp).order_by(FollowUp.scheduled_date)))
    rescheduled_apps = _rescheduled_follow_up_application_ids(db)
    rows = []
    due_today = due_this_week = overdue = upcoming = 0
    for fu in follow_ups:
        state = follow_up_state(fu, today)
        lifecycle_state = lifecycle.follow_up_lifecycle_state(
            fu,
            rescheduled=fu.application_id in rescheduled_apps,
            today=today,
        )
        app = db.get(Application, fu.application_id) if fu.application_id else None
        job = db.get(Job, app.job_id) if app else None
        days_late = None
        if fu.scheduled_date is not None and fu.scheduled_date < today:
            days_late = (today - fu.scheduled_date).days
        rows.append(
            {
                "id": fu.id,
                "application_id": fu.application_id,
                "job_title": job.title if job else None,
                "company": job.company if job else None,
                "scheduled_date": fu.scheduled_date.isoformat() if fu.scheduled_date else None,
                "reminder_date": fu.reminder_date.isoformat() if fu.reminder_date else None,
                "completed_date": fu.completed_date.isoformat() if fu.completed_date else None,
                "state": state,
                "lifecycle_state": lifecycle_state,
                "status": (fu.status or "PENDING").upper(),
                "priority": (fu.priority or "MEDIUM").upper(),
                "reason": (fu.reason or "SUBMISSION_FOLLOW_UP").upper(),
                "trigger_status": fu.trigger_status,
                "trigger_key": fu.trigger_key,
                "application_status": app.lifecycle_status if app else None,
                "application_source": app.application_source if app else None,
                "resume_name": (app.resume_name if app else None),
                "resume_version": (app.resume_version if app else None),
                "days_late": days_late,
                "overdue": state == "DUE" and fu.scheduled_date is not None
                and fu.scheduled_date < today,
                "notes": fu.notes,
            }
        )
        if state == "DUE" and fu.scheduled_date == today:
            due_today += 1
        if state == "DUE" and fu.scheduled_date is not None and fu.scheduled_date < today:
            overdue += 1
        if (
            state in ("PENDING", "DUE")
            and fu.scheduled_date is not None
            and today <= fu.scheduled_date <= today + timedelta(days=7)
        ):
            due_this_week += 1
        if state == "PENDING" and fu.scheduled_date is not None and fu.scheduled_date > today:
            upcoming += 1
    return {
        "date_basis": "scheduled_date compared to today (local calendar date).",
        "due_today": due_today,
        "due_this_week": due_this_week,
        "overdue": overdue,
        "upcoming": upcoming,
        "completed": sum(1 for r in rows if r["status"] == "COMPLETED"),
        "cancelled": sum(1 for r in rows if r["status"] == "CANCELLED"),
        "skipped": sum(1 for r in rows if r["status"] == "SKIPPED"),
        "total": len(follow_ups),
        "items": rows,
    }


def _rescheduled_follow_up_application_ids(db: Session) -> set[int]:
    rows = db.execute(
        select(ApplicationEvent.application_id)
        .where(ApplicationEvent.event_type == "FOLLOW_UP_RESCHEDULED")
        .distinct()
    ).all()
    return {int(app_id) for (app_id,) in rows}


def follow_ups_list(
    db: Session,
    *,
    status: str | None = None,
    priority: str | None = None,
    due: bool = False,
    overdue: bool = False,
    application_id: int | None = None,
    company: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Filterable follow-up list for the Phase 9 follow-up API.

    Every filter is optional; ``due``/``overdue`` act on the derived
    lifecycle state (DUE/OVERDUE), ``status`` on the stored status, and
    dates on ``scheduled_date`` (inclusive).
    """
    body = follow_up_summary(db)
    items = body["items"]
    if status:
        want = status.upper()
        if want not in ("PENDING", "COMPLETED", "CANCELLED", "SKIPPED"):
            raise ValueError(
                "status must be one of PENDING, COMPLETED, CANCELLED, SKIPPED"
            )
    else:
        want = None

    def active_state(name: str) -> bool:
        return name in ("DUE", "OVERDUE", "SCHEDULED", "RESCHEDULED")

    def matches(row: dict) -> bool:
        if want:
            stored = row["status"]
            if want == "PENDING":
                if not active_state(row["lifecycle_state"]):
                    return False
            elif stored != want:
                return False
        if priority and row["priority"] != priority.upper():
            return False
        if due and row["lifecycle_state"] != "DUE":
            return False
        if overdue and row["lifecycle_state"] != "OVERDUE":
            return False
        if application_id is not None and row["application_id"] != application_id:
            return False
        if company and not _contains_any((row["company"] or ""), company):
            return False
        if from_date or to_date:
            if not row["scheduled_date"]:
                return False
            when = date.fromisoformat(row["scheduled_date"])
            if from_date and when < date.fromisoformat(from_date):
                return False
            if to_date and when > date.fromisoformat(to_date):
                return False
        return True

    filtered = [row for row in items if matches(row)]
    priorities = {"OVERDUE": 0, "DUE": 1, "RESCHEDULED": 2, "SCHEDULED": 3,
                  "COMPLETED": 4, "SKIPPED": 5, "CANCELLED": 6}
    filtered.sort(
        key=lambda r: (
            priorities.get(r["lifecycle_state"], 9),
            r["scheduled_date"] or "9999-12-31",
        )
    )
    return {
        "total": len(filtered),
        "filters": {
            "status": status, "priority": priority, "due": due,
            "overdue": overdue, "application_id": application_id,
            "company": company, "from_date": from_date, "to_date": to_date,
        },
        "summary": body,
        "items": filtered,
    }


# ---------------------------------------------------------------------------
# Application list rows (tracking table)
# ---------------------------------------------------------------------------


def tracking_rows(
    db: Session,
    *,
    status: str | None = None,
    company: str | None = None,
    role: str | None = None,
    location: str | None = None,
    source: str | None = None,
    resume: str | None = None,
    follow_up: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sort: str = "newest",
) -> list[dict]:
    apps = _applications(db)
    rows = []
    for app in apps:
        job = db.get(Job, app.job_id)
        job_title = job.title if job else None
        job_company = job.company if job else None
        job_location = job.location if job else None
        job_source = job.source if job else None
        if status and app.lifecycle_status != status:
            continue
        if company and not _contains_any((job_company or ""), company):
            continue
        if role and not _contains_any((job_title or ""), role):
            continue
        if location and not _contains_any((job_location or ""), location):
            continue
        if source and job_source != source:
            continue
        if resume and not _contains_any((app.resume_name or ""), resume):
            continue
        if from_date or to_date:
            when = app.applied_date or (app.created_at.date() if app.created_at else None)
            if when is not None:
                if from_date and when < date.fromisoformat(from_date):
                    continue
                if to_date and when > date.fromisoformat(to_date):
                    continue

        fu = db.scalar(
            select(FollowUp)
            .where(FollowUp.application_id == app.id)
            .order_by(FollowUp.scheduled_date)
            .limit(1)
        )
        fu_state = follow_up_state(fu) if fu else None
        if follow_up:
            if follow_up == "NONE" and fu is not None:
                continue
            if follow_up != "NONE" and (fu is None or (follow_up not in fu_state)):
                continue

        last = db.scalar(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id)
            .order_by(ApplicationEvent.event_timestamp.desc(), ApplicationEvent.id.desc())
            .limit(1)
        )
        days_waiting = None
        if app.applied_date is not None:
            days_waiting = (_today() - app.applied_date).days

        rows.append(
            {
                "id": app.id,
                "job_id": app.job_id,
                "job_title": job_title or "Untitled role",
                "company": job_company,
                "role": job_title,
                "location": job_location,
                "source": job_source,
                "status": app.lifecycle_status,
                "legacy_status": app.status,
                "applied_date": app.applied_date.isoformat() if app.applied_date else None,
                "days_waiting": days_waiting,
                "created_at": app.created_at.isoformat() if app.created_at else None,
                "resume_id": app.resume_id,
                "resume_name": app.resume_name,
                "resume_version": app.resume_version,
                "notes": app.notes,
                "follow_up_state": fu_state,
                "follow_up_id": fu.id if fu else None,
                "follow_up_date": (
                    fu.scheduled_date.isoformat() if fu and fu.scheduled_date else None
                ),
                "last_event": last.event_type if last else None,
                "last_event_at": (
                    last.event_timestamp.isoformat()
                    if last and last.event_timestamp
                    else None
                ),
            }
        )

    def sort_key(row):
        if sort == "oldest":
            return row["applied_date"] or row["created_at"] or "", row["id"]
        if sort == "waiting":
            return -(row["days_waiting"] if row["days_waiting"] is not None else 0), row["id"]
        if sort == "follow_up_due":
            importance = {"DUE": 0, "PENDING": 1, "COMPLETED": 2, "CANCELLED": 3}
            return (
                importance.get(row["follow_up_state"], 4),
                row["follow_up_date"] or "9999-12-31",
                row["id"],
            )
        return row["applied_date"] or row["created_at"] or "", -row["id"]

    rows.sort(key=sort_key, reverse=(sort == "newest"))
    return rows


# ---------------------------------------------------------------------------
# Response-time breakdowns (Phase 9)
# ---------------------------------------------------------------------------


def response_time_breakdowns(db: Session) -> dict:
    """Days from submission to first real response, split per dimension.

    Only timestamps backed by immutable events (with the legacy fallback) are
    counted; nothing is invented.
    """
    apps = _applications(db)
    milestones = _milestone_dates(db, apps)
    buckets = {
        "role": {},
        "location": {},
        "discovery_source": {},
        "submission_source": {},
        "company": {},
        "resume": {},
    }
    days_by_app: dict[int, int] = {}

    def add(dimension: str, label: str, days: int) -> None:
        buckets[dimension].setdefault(label, []).append(days)

    for app in apps:
        job = db.get(Job, app.job_id)
        reached = milestones.get(app.id, {})
        submit_dates = [
            reached[s]
            for s in ("SUBMITTED", "SUBMISSION_CONFIRMED")
            if s in reached
        ]
        response_dates = [
            reached[s]
            for s in ("RESPONSE_RECEIVED", "INTERVIEW", "OFFER")
            if s in reached
        ]
        if not submit_dates or not response_dates:
            continue
        submit = min(submit_dates)
        respond = min(response_dates)
        days = (respond - submit).days
        days_by_app[app.id] = days
        role = job.title if job else None
        if role:
            add("role", role, days)
        loc = job.location if job else None
        if loc:
            add("location", loc, days)
        src = job.source if job else None
        if src:
            add("discovery_source", src, days)
        if app.application_source:
            add("submission_source", app.application_source, days)
        if job and job.company:
            add("company", company_service.display_name_for(job.company) or job.company, days)
        if app.resume_name or app.resume_id:
            label = app.resume_name or f"Resume #{app.resume_id}"
            if app.resume_version:
                label = f"{label} · {app.resume_version}"
            add("resume", label, days)

    return {
        "basis": (
            "Days between submission and first real response "
            "(RESPONSE_RECEIVED / INTERVIEW / OFFER milestone)."
        ),
        "overall": _stat(list(days_by_app.values())),
        "dimensions": {
            name: [
                {"label": label, **_stat(days_list)}
                for label, days_list in sorted(group.items(), key=lambda kv: -len(kv[1]))
            ]
            for name, group in buckets.items()
        },
    }


# ---------------------------------------------------------------------------
# Insights engine (Phase 9) — deterministic, evidence-only
# ---------------------------------------------------------------------------


def insights(db: Session) -> dict:
    """Deterministic insights derived strictly from verified analytics.

    Every insight carries its ``metrics`` evidence. No LLM, no guessing.
    """
    items: list[dict] = []
    funnel_data = funnel(db)
    sources = source_performance(db)
    resumes = resume_performance(db)
    follow_ups = follow_up_summary(db)
    response = response_time_breakdowns(db)

    steps = {s["step"]: s["count"] for s in funnel_data["steps"]}
    submitted = steps.get("SUBMITTED") or 0
    if submitted == 0:
        return {
            "items": [
                {
                    "key": "no_data",
                    "severity": "info",
                    "title": "Not enough data for insights yet",
                    "message": (
                        "Track applications, run executions, and record responses "
                        "to unlock deterministic insights."
                    ),
                    "metrics": {"submitted": 0},
                }
            ],
            "basis": "Insights only echo verified analytics; none are inferred.",
        }

    if response["overall"].get("measured", 0) > 0:
        items.append(
            {
                "key": "response_speed",
                "severity": "info",
                "title": "Response speed",
                "message": (
                    f"Median time from submission to first response is "
                    f"{response['overall']['median_days']} days across "
                    f"{response['overall']['measured']} responses."
                ),
                "metrics": response["overall"],
            }
        )

    best_discovery = [
        s
        for s in sources["discovery"]
        if s["submitted"] >= SMALL_SAMPLE_THRESHOLD
        and s["source_quality"]["score"] is not None
    ]
    if best_discovery:
        best = max(best_discovery, key=lambda s: s["source_quality"]["score"])
        items.append(
            {
                "key": "best_discovery_source",
                "severity": "success" if best["source_quality"]["label"] in
                ("EXCELLENT SIGNAL", "GOOD") else "info",
                "title": "Strongest discovery source",
                "message": (
                    f"{best['label']} shows a {best['source_quality']['label']} "
                    f"signal (quality {best['source_quality']['score']}/100) over "
                    f"{best['submitted']} submissions."
                ),
                "metrics": best,
            }
        )

    qualified_resumes = [
        r for r in resumes if r["submitted"] >= SMALL_SAMPLE_THRESHOLD
    ]
    if qualified_resumes:
        best_resume = max(
            qualified_resumes, key=lambda r: r["composite_score"]
        )
        items.append(
            {
                "key": "best_resume",
                "severity": "success" if best_resume["rank_label"] in
                ("STRONGER SIGNAL", "PROMISING") else "info",
                "title": "Strongest resume signal",
                "message": (
                    f"{best_resume['label']} has the strongest verified signal "
                    f"(composite {best_resume['composite_score']}) over "
                    f"{best_resume['submitted']} submissions."
                ),
                "metrics": {
                    "label": best_resume["label"],
                    "composite_score": best_resume["composite_score"],
                    "submitted": best_resume["submitted"],
                },
            }
        )

    overdue = follow_ups.get("overdue", 0)
    if overdue:
        items.append(
            {
                "key": "overdue_follow_ups",
                "severity": "warning",
                "title": "Overdue follow-ups",
                "message": (
                    f"{overdue} follow-up(s) are overdue; handle them or skip "
                    "them to keep the queue current."
                ),
                "metrics": {"overdue": overdue},
            }
        )

    limited = sum(1 for r in resumes if r["limited_data"]) + sum(
        1 for s in sources["discovery"] if s["limited_data"]
    )
    items.append(
        {
            "key": "sample_health",
            "severity": "info",
            "title": "Sample health",
            "message": (
                f"{limited} resume/source group(s) have a sample below "
                f"{SMALL_SAMPLE_THRESHOLD} and are flagged 'Limited data'."
                if limited
                else f"All resume and source samples met the n={SMALL_SAMPLE_THRESHOLD} threshold."
            ),
            "metrics": {"limited_groups": limited, "threshold": SMALL_SAMPLE_THRESHOLD},
        }
    )

    return {
        "items": items,
        "basis": "Insights only echo verified analytics; none are inferred.",
    }


def _contains_any(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()
