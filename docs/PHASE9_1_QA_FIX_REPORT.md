# PHASE 9.1 QA FIX REPORT

**Date:** 2026-09-07
**Scope:** Fix 4 actionable findings from the Phase 9 full-system QA pass
**Commits:** All fixes on top of `7f00e60` (Phase 9); NOT committed

---

## DEF1 — P1: Execution-confirmed submission stuck at DISCOVERED

### Root Cause

`_upsert_application_tracker` (executor.py:828) created new `Application` rows at `lifecycle_status="DISCOVERED"` then called `move_lifecycle(db, row, "SUBMISSION_CONFIRMED")`. Since `DISCOVERED → SUBMISSION_CONFIRMED` is not a legal edge in the state machine (`TRANSITIONS["DISCOVERED"] = {SHORTLISTED, WITHDRAWN, EXPIRED, CANCELLED}`), `move_lifecycle` raised `TrackingError`. The executor caught it and recorded a misleading "Repeat submission" fallback event — even though this was the **first** confirmation. The row stayed at DISCOVERED.

When `move_lifecycle` was called on the new row at DISCOVERED → SUBMISSION_CONFIRMED, it raised TrackingError because that transition isn't legal. The fallback event was always recorded, even for first-time confirmations.

### Fix

`backend/app/application_execution/executor.py`:
1. New rows are created at `lifecycle_status=target_status` (e.g. SUBMISSION_CONFIRMED) instead of DISCOVERED.
2. The `APPLICATION_CREATED` event records `new_status=target_status`.
3. A `new_row` flag tracks whether this is a fresh creation.
4. After `move_lifecycle`, if the status already matched (early return) **and** this is a new row, the executor manually records the milestone event and creates the follow-up — restoring the audit trail and follow-up scheduling that `move_lifecycle`'s early return skipped.
5. The "Repeat submission" fallback only fires when `before_status != target_status` (genuinely a second confirmation on an existing row past the target).

### Tests

`tests/test_phase9_1_qa_fixes.py` — 4 tests:
- `test_new_row_lands_at_submission_confirmed`: lifecycle_status == SUBMISSION_CONFIRMED after first confirm
- `test_first_confirm_records_correct_events`: APPLICATION_CREATED + SUBMISSION_CONFIRMED events, no "Repeat submission"
- `test_first_confirm_schedules_follow_up`: follow-up created with correct reason/priority
- `test_repeat_confirm_no_duplicate_follow_up`: second confirm rejected (409), no duplicate follow-up

### Browser Verification

Dashboard, /applications, /applications/track, /analytics — all render correctly. No console errors.

---

## DEF2 — P2: Finished follow-up actions return HTTP 500

### Root Cause

`complete_follow_up` and `cancel_follow_up` routes (tracking.py:386–428) did not wrap domain calls in `try/except _handle(...)`. The lifecycle functions raise `TrackingError(409)` for finished follow-ups, but without the `_handle` wrapper the exception propagated as a generic 500. The sibling routes (`skip`, `restore`, `reschedule`) all used the wrapper correctly.

### Fix

`backend/app/api/routes/tracking.py`:
- Wrapped `complete_follow_up` route body in `try: ... except Exception as exc: raise _handle(exc) from exc`
- Wrapped `cancel_follow_up` route body in the same pattern

### Tests

`tests/test_phase9_1_qa_fixes.py` — 4 tests:
- `test_complete_on_completed_returns_409`: HTTP 409, "already finished"
- `test_cancel_on_cancelled_returns_409`: HTTP 409, "already finished"
- `test_complete_on_pending_succeeds`: HTTP 200
- `test_cancel_on_pending_succeeds`: HTTP 200

---

## DEF3 — P2: Invalid target status returns HTTP 500

### Root Cause

`set_status_manual` calls `app_status.validate_target_status(target)` which raises `InvalidStatusError` (not a `TrackingError` or `ValueError`). The `_handle` function only mapped `TrackingError` and `ValueError`, so `InvalidStatusError` fell through to the default 500 path. The existing inline import at tracking.py:63 already passed `InvalidStatusError` to `_handle`, confirming the function was expected to handle it — but the handler lacked the branch.

### Fix

`backend/app/api/routes/tracking.py`:
- Added `InvalidStatusError` import at module level
- Added `isinstance(e, InvalidStatusError)` branch to `_handle`, returning `HTTPException(status_code=422, detail=f"Invalid application status: {e.value!r}")`
- Removed redundant inline import at the old line 63

### Tests

`tests/test_phase9_1_qa_fixes.py` — 3 tests:
- `test_invalid_status_string_returns_422`: "BOGUS_STATUS" → 422
- `test_valid_illegal_transition_returns_409`: SUBMISSION_CONFIRMED→EXECUTING → 409
- `test_valid_legal_transition_succeeds`: SUBMISSION_CONFIRMED→RESPONSE_RECEIVED → 200

---

## DEF4 — P3: Dashboard Avg match / Avg opportunity always "—"

### Root Cause

Frontend `Dashboard.jsx:399,403` read `stats.matches.avg_match_score` / `stats.matches.avg_opportunity_score`. Backend `/jobs/stats` returned `matches.average_match_score` / `matches.average_opportunity_score` (note `average_` not `avg_`). The property names didn't match, so the nullish coalescing fell through to "—".

### Fix

`frontend/src/pages/Dashboard.jsx`:
- Changed `stats?.matches?.avg_match_score` → `stats?.matches?.average_match_score`
- Changed `stats?.matches?.avg_opportunity_score` → `stats?.matches?.average_opportunity_score`

### Tests

`tests/test_phase9_1_qa_fixes.py` — 1 test:
- `test_jobs_stats_returns_correct_field_names`: verifies `average_match_score` / `average_opportunity_score` exist and `avg_match_score` / `avg_opportunity_score` do not

### Frontend Verification

Dashboard now renders "Avg match 82/100" and "Avg opportunity 73/100" instead of "—".

---

## Interview Thank-You

**Preserved.** No changes made to the interview thank-you suppression behavior. The response-gate in `create_follow_up` (line ~494) correctly prevents thank-you follow-ups when the application already has a response. This is documented, tested (`test_no_follow_up_after_offer_or_response`), and was verified during the QA pass.

---

## Regression

| Gate | Result |
|---|---|
| `pytest` | **PASS — 356 tests** (344 original + 12 new) |
| `ruff check app tests` | **PASS — clean** |
| `npm run build` | **PASS** (vite 6.4.3) |
| Playwright (7 pages) | **PASS — 7/7** (0 console errors) |

---

## Data Integrity

- No historical events were modified.
- No QA mock data was deleted or altered.
- The 4 files changed are:
  - `backend/app/application_execution/executor.py` (+21 lines, −7 lines)
  - `backend/app/api/routes/tracking.py` (+14 lines, −7 lines)
  - `frontend/src/pages/Dashboard.jsx` (+2 lines, −2 lines)
  - `tests/test_phase9_1_qa_fixes.py` (new, 420 lines)

---

## Remaining Issues

1. **Follow-up `action_type` column is NOT NULL** — the test helper needed `action_type="follow_up"` to avoid IntegrityError. This is a schema constraint, not a defect, but worth noting that direct ORM inserts into `follow_ups` must include `action_type`.

2. **Funnel "Discovered" counts all jobs (38) not tracked applications (5)** — by design (first-reach model with DISCOVERED = total jobs). Not a defect.

3. **`React.StrictMode` double-fetch + favicon 404** — dev-only, benign.

---

## Git

NOT committed. All changes are in the working tree:
- `backend/app/application_execution/executor.py`
- `backend/app/api/routes/tracking.py`
- `frontend/src/pages/Dashboard.jsx`
- `tests/test_phase9_1_qa_fixes.py` (new file)
