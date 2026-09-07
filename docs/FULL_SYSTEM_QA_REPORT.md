# FULL SYSTEM QA REPORT — Job Agent

**Date:** 2026-09-07
**Phase under test:** Phase 9 (follow-up engine + analytics) on top of Phases 1–8
**Commit under test:** `7f00e60` (Phase 9), clean working tree at start
**Backend:** `http://localhost:8000` (health `{"status":"ok","version":"0.1.0","database":true}`)
**Frontend:** `http://localhost:5173`
**QA mode:** black-box, read-only DB, no code changes, no real submissions/emails/external sites

---

## Verdict

### PASS WITH ISSUES

Phase 9's core features work end-to-end: the follow-up engine (schedule → reschedule → skip → restore → complete → cancel, auto-scheduling for SUBMITTED and INTERVIEW, trigger-key deduplication) and the analytics suite (funnel, response times, source quality, resume performance, follow-up health, insights) both verified correct with exact arithmetic. However, the QA pass surfaced **two defect clusters in tracking API error handling** (500s where 4xx are contractually expected, including one data-consistency bug around fresh execution confirmations) plus one dashboard API/UI contract bug. These should be fixed before Phase 10 begins.

---

## 1. Automated Gates

| Gate | Result |
|---|---|
| `pytest` (backend) | **PASS — 344 tests** |
| `ruff check app tests` | **PASS — clean** |
| `npm run build` (frontend) | **PASS** (vite 6.4.3; stderr npm-notice lines are noise) |

---

## 2. Browser UI Verification

All 7 primary pages verified via Playwright accessibility snapshots + console + network monitoring.

| Page | Result | Notes |
|---|---|---|
| `/` Dashboard | PASS | Funnel, follow-ups card, top companies, backend status; all API 200 |
| `/jobs` | PASS | 36→38 jobs, filters, Remote filter narrows correctly |
| `/applications` | PASS | Status + follow-up + sort filters, table, funnel footer |
| `/applications/track/1` | PASS | Overview/timeline/responses/interviews/offers/update-status/follow-ups/notes |
| `/applications/packages` | PASS | NEEDS_REVIEW / NOT_READY / APPROVED states |
| `/applications/1/execute` | PASS | Full execution trail, preview, modes, steps, evidence |
| `/analytics` | PASS | All 10+ analytics blocks render; deterministic insights |

Re-verified after golden path: Dashboard shows 38 jobs / 5 submitted / OFFER(1) funnel + upcoming follow-up card; `/applications` lists the 2 QA apps (OFFER→WITHDRAWN, RESPONSE_RECEIVED); `/applications/track/5` renders the full golden-path timeline incl. auto-scheduled "Interview Thank You"; `/analytics` reflects all QA data.

**Console:** 0 errors on every page. Two benign items: missing `/favicon.ico` (404) and React Router v7 future-flag warnings. Dev-only `React.StrictMode` causes double API fetches (expected).

---

## 3. Golden Path (live, mock driver, real API)

Seeded two QA jobs through the app's real `job_service.insert_jobs` path (`source=mock`, `mock://` application URLs so the MockBrowserDriver handles them).

### Job 51 — "QA Golden Path Developer" (QACo Careers) → application 4
match 89 / APPLY, opportunity 83 / APPLY, quality 70, VERY_FRESH → package 4 prepared (NEEDS_REVIEW / NOT_READY, no resume on file) → approved → executed (mock, PERMITTED_BROWSER, 9 fields detected / 6 filled / 3 needing review, AWAITING_APPROVAL + warnings) → approve → SUBMISSION_CONFIRMED (`https://mock.test/simple-form/thank-you`, ref REF-SIMPLE-FORM).

Status chain walked via PATCH (all legal): DISCOVERED → SHORTLISTED → PREPARING → READY_FOR_REVIEW → APPROVED → EXECUTION_READY → EXECUTING → SUBMITTED → SUBMISSION_CONFIRMED. Entering SUBMITTED auto-scheduled submission follow-up (+7 d).

Follow-up lifecycle exercised: duplicate schedule → 409; reschedule → OK; skip → OK; restore → OK; complete → OK (completed 2026-09-07).

Response recorded (RECRUITER_CONTACT, 2026-09-08) → auto-advance RESPONSE_RECEIVED; interview recorded (VIDEO, round 1, 2026-09-12) → auto-advance INTERVIEW; offer recorded (2026-09-20) → auto-advance OFFER; PATCH WITHDRAWN `override=true` → STATUS_CORRECTED (OFFER → WITHDRAWN) to exercise the correction path.

### Job 52 — "QA Interview-flow Developer" (QACo Recruiting) → application 5
Same prepare/approve/execute/confirm cycle → status chain walked to SUBMISSION_CONFIRMED → **interview recorded with NO prior response** → verified the `INTERVIEW_THANK_YOU` follow-up **auto-scheduled live**: HIGH priority, scheduled `interview_date + 1 d` (2026-09-13), trigger key `app:5:INTERVIEW_THANK_YOU:2` (embeds the interview record id; dedupe-safe). Response then recorded → RESPONSE_RECEIVED; submission follow-up (fu2) left PENDING; fu3 (thank-you) cancelled to exercise the cancel endpoint; a note was added.

---

## 4. Follow-Up Engine Verification

| Scenario | Result |
|---|---|
| Auto-schedule on SUBMITTED (MEDIUM, SUBMISSION_FOLLOW_UP, +7 d) | PASS |
| Auto-schedule on INTERVIEW (HIGH, INTERVIEW_THANK_YOU, +1 d, per-record trigger key) | PASS |
| Duplicate schedule | 409 "Follow-up already exists, or the application is rejected/withdrawn/has a response." |
| Reschedule / Skip / Restore / Complete / Cancel | PASS (lifecycle states SCHEDULED / RESCHEDULED / SKIPPED / COMPLETED / CANCELLED) |
| Action on finished follow-up (skip on completed, skip/complete on cancelled) | 409 "Follow-up already finished." — **but via HTTP 500 for `complete` and `cancel` (DEF2)** |
| Filters: status=PENDING/COMPLETED, overdue, date window, priority | PASS |
| Summary/health: due 0 / upcoming 1 / completed 1 / cancelled 1 | PASS |

---

## 5. Analytics Verification

| Block | Result |
|---|---|
| Funnel (first-reach milestone model) | PASS — 38 / 2 / 2 / 2 / 2 / 5 / 5 / 2 / 2 / 1; rates 5.3% / 13.2% / 100% / 40% / 40% / 20% |
| Applications over time | PASS — W36: 3, W37: 2 |
| Response times + breakdowns | PASS — response 2×0d, interview 2×0d, offer 1×0d; per-role/location/source/company breakdowns |
| Source quality (exact math) | PASS — mock n=5 → PROMISING 46.0 (=0.15·100+0.40·40+0.30·40+0.15·20); company_career n=4 → LIMITED DATA 53.8; generic n=1 → LIMITED DATA |
| Recommended resume | PASS — honest no-data message (no resumes exist) |
| Resume performance | PASS — only "No resume" row; rank LIMITED DATA at n=5/composite 60 is per-spec banding |
| Follow-up health | PASS — 0 / 0 / 1 / 1 / 1 / 0, total 3 |
| Insights | PASS — deterministic, evidence-only (no invented claims) |

---

## 6. Edge & Negative Cases

| Scenario | Result |
|---|---|
| Confirm on already-confirmed run | 400 "Execution is 'SUBMISSION_CONFIRMED'; only a paused run can be confirmed." |
| Illegal transition via PATCH | 409 "Illegal transition … Use override … (STATUS_CORRECTED)." |
| Override transition | PASS — OFFER→WITHDRAWN, `STATUS_CORRECTED` event |
| POST on PATCH-only status route | 405 (expected — docs say PATCH) |
| Nonexistent application / follow-up | 404 |
| Invalid response category | 422 |
| Invalid follow-up reason/priority | 422 via tests; live path returns response-gate 409 first (see DEF5) |
| Missing resume | Package NOT_READY / NEEDS_REVIEW; execution warning "no resume" |
| Duplicate mock execution | Dedupe by trigger key / existing-follow-up guards (409) |
| Jobs banding ("Opportunity 48 → SKIP") | Consistent with thresholds; assumed by design — not a verified defect |

---

## 7. Database Integrity (read-only)

| Check | Result |
|---|---|
| Counts | jobs 38, apps 5, packages 5, executions 5, follow-ups 3, events 40, responses 2, interviews 2, offers 1, resumes 0, profiles 1 |
| Orphan rows (follow-ups/events/responses/interviews/offers → applications) | 0 |
| NULL trigger_key / trigger_status / priority / reason | 0 |
| Duplicate trigger keys | 0 |
| Invalid follow-up status / application lifecycle status | 0 |
| Timeline ↔ status consistency | All milestone events agree with current statuses except the documented executor artifact (DEF1) |

Application-5 interview walk proved `_move_toward_target` transitions through intermediate legal states (SUBMISSION_CONFIRMED → RESPONSE_RECEIVED → INTERVIEW) while recording real events.

---

## 8. Findings & Defects

### DEF1 — P1 (data-consistency): Fresh execution-confirmed submissions get stuck at DISCOVERED with a misleading event
- **Symptom:** When a *new* application is confirmed by execution (`_upsert_application_tracker`), the tracking row is created at `lifecycle_status="DISCOVERED"`. The state machine has no legal `DISCOVERED → SUBMISSION_CONFIRMED` edge, so `move_lifecycle` raises `TrackingError`; the executor catches it and records `SUBMISSION_CONFIRMED: DISCOVERED → DISCOVERED` with note **"Repeat submission for execution #4/#5"** — implying a duplicate when the app was *not* a repeat. Row stays at DISCOVERED (`legacy_status="submitted"`).
- **Reproduced:** apps 4 (event id 8) and 5 (event id 25).
- **Root cause:** `executor.py::_upsert_application_tracker` hardcodes `new_status="DISCOVERED"` for new rows and only tries to advance a single target; `application_tracking/status.py::TRANSITIONS` has no DISCOVERED→SUBMISSION_CONFIRMED edge; the fallback writes a mislabeled transparent event. Apps 1–3 only look correct because import/backfill set SUBMISSION_CONFIRMED directly.
- **Impact:** Any auto-driven submission lands in a wrong state and both the UI (Overview fine on app 5 only because QA manually walked the chain) and analytics mis-model it until a human PATCHes the status.
- **Suggested fix:** create new tracker rows at their implied stage, or add the legal edge / a non-misleading event.

### DEF2 — P2 (error-handling): 500 on follow-up `complete`/`cancel` for a finished follow-up
- **Symptom:** `POST /tracking/follow-ups/{id}/complete` (and `cancel`) on an already-finished follow-up → **HTTP 500 Internal Server Error** instead of the contractually-specified 409 ("Follow-up already finished."). `skip`/`restore`/`reschedule` correctly return 409.
- **Root cause:** `complete_follow_up`/`cancel_follow_up` raise `TrackingError(409)`, but the routes in `tracking.py` (lines 386–428) do **not** wrap the call in `try/except _handle(...)` — the sibling routes do. Live evidence: `complete` on cancelled fu3 → 500; `cancel` on finished would 500 the same way.
- **Impact:** Client can't rely on 4xx semantics; generic 500 pollutes the UI error path and logs.

### DEF3 — P2 (error-handling): 500 on invalid target status
- **Symptom:** `PATCH /tracking/applications/{id}/status` with `{"target_status":"BOGUS"}` → **HTTP 500** "Invalid application status: 'BOGUS'" instead of 422.
- **Root cause:** `set_status_manual` validates via `app_status.validate_target_status`, which raises `InvalidStatusError` (neither `TrackingError` nor `ValueError`), and the route doesn't catch it.
- **Impact:** Invalid input is an internal server error; breaks the 422 contract the rest of the API follows.

### DEF4 — P3 (UI/API contract): Dashboard "Avg match" / "Avg opportunity" always show "—"
- **Symptom:** Dashboard Match Intelligence renders `Avg match: —` / `Avg opportunity: —` although `GET /jobs/stats` returns `matches.average_match_score: 82`, `matches.average_opportunity_score: 73` (Avg quality renders fine as 50/100).
- **Root cause:** `frontend/src/pages/Dashboard.jsx:399,403` reads `stats.matches.avg_match_score` / `avg_opportunity_score`, backend emits `average_match_score` / `average_opportunity_score`.
- **Impact:** Cosmetic but user-visible; one-line fix.

### DEF5 — P3 (observation): response-gate precedence masks invalid follow-up parameter errors
- `create_follow_up` returns 409 (response gate) before validating reason/priority, so on an app that already has a response, an invalid `reason`/`priority` yields 409 instead of 422. Tests document the gates; behavior is consistent but noisy.

### Observations (not defects)
- **Interview thank-you suppression (documented design, verified live):** `create_follow_up` returns `None` when the application already has a response — so no `INTERVIEW_THANK_YOU` is created when a response preceded the interview, which is the *common* path (live-confirmed on app 4; contrast app 5 where no response → thank-you auto-created). Covered by `test_phase9_follow_ups.py`. Product trade-off worth a conscious decision.
- Funnel "Discovered" counts **all jobs (38)**, not tracked applications (5); `application_rate` denominator is therefore jobs (5/38 = 13.2%). Consistent with baseline (36/3); scale by design.
- Withdrawn-after-offer apps keep counting in the OFFER stage (first-reach model). Consistent by design.
- `React.StrictMode` double-fetch + `/favicon.ico` 404: benign, dev-only.
- `/jobs` banding thresholds (e.g., Opportunity 48 → SKIP): believed by design; not verified as a bug.

---

## 9. QA Data Left in the Database

| Entity | Rows |
|---|---|
| QA jobs | 51 ("QA Golden Path Developer", QACo Careers), 52 ("QA Interview-flow Developer", QACo Recruiting) — source `mock` |
| Tracking applications | 4 (QACo Careers → **WITHDRAWN** after override test), 5 (QACo Recruiting → RESPONSE_RECEIVED) |
| Packages / executions | 4 & 5 (mock driver) |
| Follow-ups | 1 (completed), 2 (pending, submission), 3 (cancelled, interview thank-you) |
| Responses / interviews / offers | 2 / 2 / 1 (+ 1 note on app 5) |

These are `source="mock"` so they are excluded from export/forwarding logic. Cleanup (delete jobs 51–52 / apps 4–5 or re-run the golden path) is a follow-up; QA intentionally left them to preserve the demonstrated state.

---

## 10. Recommended Actions

1. **Fix DEF1** (tracker row creation / misleading "repeat submission" event) — qualifies release for real auto-submission flows.
2. **Fix DEF2 & DEF3** (wrap follow-up complete/cancel + status PATCH in `_handle`) — quick, restores 4xx contract.
3. **Fix DEF4** (Dashboard avg match/opportunity field names) — one-liner.
4. Decide on DEF5 / interview thank-you trade-off deliberately.
5. Re-run `pytest` + browser pass after fixes; my recommended order is DEF1 → DEF2/3 → DEF4.