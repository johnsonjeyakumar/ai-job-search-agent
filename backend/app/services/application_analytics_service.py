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
) -> list[dict]:
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
# Follow-up summary
# ---------------------------------------------------------------------------


def follow_up_summary(db: Session) -> dict:
    today = _today()
    follow_ups = list(db.scalars(select(FollowUp).order_by(FollowUp.scheduled_date)))
    rows = []
    due_today = due_this_week = overdue = upcoming = 0
    for fu in follow_ups:
        state = follow_up_state(fu, today)
        app = db.get(Application, fu.application_id) if fu.application_id else None
        job = db.get(Job, app.job_id) if app else None
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
                "status": (fu.status or "PENDING").upper(),
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
        "total": len(follow_ups),
        "items": rows,
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


def _contains_any(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()
