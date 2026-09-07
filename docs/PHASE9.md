# Phase 9 — Follow-Up Automation Engine + Resume & Job-Source Performance Analytics

Status: ✅ implemented, tests + lint + build green, migration applied to the dev
DB, UI verified (read-only browser). **No commit was made** — Phase 9 changes are
left uncommitted for the user to review and commit.

Migration: `b3e7d2f1a9c4_phase9_follow_up_and_source_analytics.py`
(down_revision `a1b2c3d4e5f6`).

## Scope

- **Follow-up automation engine** on top of Phase 8 application tracking:
  deterministic scheduling, typed reasons/priorities, dedupe keys, derived due
  states, and skip / restore / cancel / complete / reschedule actions.
- **Resume performance analytics** (historical snapshots kept per application),
  a **recommended resume**, and **job-source intelligence** (discovery +
  submission sources with an explicit quality score).
- **Response-time breakdowns** and a deterministic **insights** engine.
- New **Analytics** page + Dashboard / tracking-detail follow-up UX.

Not in scope (deliberately excluded): interview prep, skill-gap learning, an ML
loop, recruiter outreach/email automation, auto mass apply, and any CAPTCHA /
anti-bot bypass. The n8n phase stays out of this phase's dependency.

## Follow-up engine

Lives in `backend/app/services/application_lifecycle_service.py`.

- `create_follow_up(...)` validates `reason` ∈ {`SUBMISSION_FOLLOW_UP`,
  `INTERVIEW_THANK_YOU`} and `priority` ∈ {`HIGH`, `MEDIUM`, `LOW`}, else 422.
- Never schedules when the application is in `_NO_FOLLOW_UP_STATUSES`
  (`REJECTED`, `WITHDRAWN`, `EXPIRED`, `CANCELLED`, `OFFER`) or already has a
  recorded response.
- Default `trigger_status` = application lifecycle status; default `trigger_key`
  = `app:{id}:{reason}:{trigger_status}` — one follow-up per reason/trigger.
- Interview thank-you: `schedule_interview_follow_up` seeds `INTERVIEW_THANK_YOU`
  (HIGH priority) from `record_interview`, keyed by the interview record, and
  scheduled `interview_date + interview_follow_up_days` (a new Preferences knob,
  default 1). `allow_extra_for_application` lets several interview thank-yous
  coexist on one application.
- Actions: `skip_follow_up` (SKIPPED + `skipped_at`), `restore_follow_up`
  (PENDING, past schedules bumped to today), `cancel_follow_up`. All write
  immutable `FOLLOW_UP_SKIPPED` / `FOLLOW_UP_RESTORED` timeline events.
- `follow_up_lifecycle_state()` derives the effective state for the UI:
  terminal status wins; past `scheduled_date` → `OVERDUE`; today → `DUE`;
  rescheduled → `RESCHEDULED`; else `SCHEDULED`. `follow_up_state()` (Phase 8)
  is unchanged.

## Analytics

Lives in `backend/app/services/application_analytics_service.py`.

- `source_performance`: discovery (`by_source`) and submission
  (`by_application_source`, captured from the executor's recorded platform) rows
  plus an explicit `_source_quality` score — `0.15*submission_rate +
  0.40*response_rate + 0.30*interview_rate + 0.15*offer_rate` with documentated
  `basis` and `LIMITED DATA` / band labels below `n=5`.
- `resume_performance` (+ `_resume_rank`): composite = interview% + offer%,
  labels `STRONGER SIGNAL` / `PROMISING` / `LIMITED DATA` / `INSUFFICIENT DATA`,
  filterable by role / location / source / company / date window.
- `recommended_resume`: highest-composite qualified resume (`n >= 5`); returns a
  plain "not enough historical data" answer otherwise — never a fabricated pick.
- `response_time_breakdowns`: days from submission to first real response, split
  by role / location / discovery source / submission source / company / resume.
- `insights`: deterministic, evidence-only items (response speed, strongest
  source/resume, overdue follow-ups, sample health); zero LLM.

## API surface (new/changed)

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/tracking/follow-ups` | Filterable follow-up list (status, priority, due, overdue, application_id, company, from_date, to_date) |
| GET | `/tracking/follow-ups/summary` | Health counts + enriched rows for widgets |
| GET / POST | `/tracking/applications/{id}/follow-ups` | List / schedule per application |
| POST | `/tracking/follow-ups/{id}/skip` / `.../restore` / `.../complete` / `.../reschedule` / `.../cancel` | Follow-up actions |
| GET | `/analytics/resumes`, `/analytics/resumes/compare`, `/analytics/recommended-resume` | Resume performance, comparison, recommendation |
| GET | `/analytics/sources/performance` | Discovery + submission quality |
| GET | `/analytics/response-times/breakdowns` | Response-time splits |
| GET | `/analytics/insights` | Deterministic insights |
| GET | `/analytics/follow-ups` | Follow-up health summary |

## Data model changes

- `Application.application_source` (String, indexed) — set from the real recorded
  execution platform; never fabricated (grouped as "No submission source").
- `FollowUp.priority`, `FollowUp.reason`, `FollowUp.trigger_status`,
  `FollowUp.trigger_key` (indexed), `FollowUp.skipped_at`.
- `Preferences.interview_follow_up_days` (default 1).
- New events `FOLLOW_UP_SKIPPED` / `FOLLOW_UP_RESTORED`.

## Frontend

- `Dashboard.jsx` — rewritten Follow-ups card: OVERDUE / DUE / UPCOMING groups,
  lifecycle-state + priority badges, reason, `days_late`, resume version, and
  Complete / Reschedule / Skip / Restore actions that call the follow-up API and
  refresh in place.
- `ApplicationTracking.jsx` — follow-ups section shows lifecycle state, priority,
  reason, trigger status, `days_late`, and skip / restore buttons alongside the
  existing actions.
- New `Analytics.jsx` page at `/analytics` (nav entry "Analytics"): funnel,
  weekly trend, response times + breakdowns, source quality, recommended resume,
  resume performance + compare, follow-up health, insights.

## Tests

- `backend/tests/test_phase9_follow_ups.py` (12 tests) — engine defaults /
  validation, terminal-status + response guards, interview thank-you scheduling,
  skip / restore semantics, lifecycle-state derivation, filter + 422 behavior.
- `backend/tests/test_phase9_resume_source_analytics.py` (11 tests) — resume rank
  labels, recommended-resume no-data vs qualified picks, source quality weights /
  bands / insufficient data, response-time breakdowns, insights determinism.

## Verification / gates

- `pytest`: **344 tests pass** (23 new Phase 9).
- `ruff check app tests`: clean.
- Frontend `npm run build`: passes.
- `alembic upgrade head` applied to the dev DB (`a1b2c3d4e5f6 → b3e7d2f1a9c4`).
- Read-only browser verification (no console errors) on `/`, `/analytics`,
  `/applications`, `/applications/track/1`, `/applications/packages`,
  `/applications/1/execute`.
- Live API smoke checks returned 200 for all new endpoints and 422 for an invalid
  `status` filter.

Servers used for verification remain running (backend :8000, frontend :5173).