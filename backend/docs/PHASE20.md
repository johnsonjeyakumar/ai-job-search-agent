# Phase 20 — Job Expiration + Preflight Hardening

**Date**: 2026-09-10
**Duration**: ~3 hours
**Tests**: 72 new (total 500 across Phases 15-20)
**Status**: ✅ COMPLETE

---

## Objective

Detect expired, closed, or changed job listings before attempting submission, and harden the preflight validation pipeline with structured results, deadline handling, identity checks, and duplicate integration.

---

## What Was Built

### `app/application_execution/preflight.py` — Core Preflight Module

**JobAvailability** enum (7 states):
- `ACTIVE` — job is live and accepting applications
- `EXPIRING_SOON` — deadline approaching (within `DEFAULT_EXPIRING_SOON_DAYS`)
- `EXPIRED` — job posting is stale or no longer listed
- `CLOSED` — position filled or explicitly closed
- `REMOVED` — page returns 404/410
- `UNAVAILABLE` — access forbidden (403)
- `UNKNOWN` — could not determine status

**ReasonCode** enum (22 machine-readable codes):
- Job state: `JOB_EXPIRED`, `JOB_CLOSED`, `JOB_REMOVED`, `JOB_UNAVAILABLE`, `JOB_STATE_UNKNOWN`, `JOB_MISMATCH`, `JOB_NOT_FOUND`
- Deadlines: `DEADLINE_PASSED`, `DEADLINE_EXPIRING_SOON`
- Duplicates: `DUPLICATE_APPLICATION`, `DUPLICATE_SUSPECTED`
- Package: `PACKAGE_MISSING`, `PACKAGE_INVALID`, `PACKAGE_NOT_APPROVED`
- Documents: `RESUME_MISSING`, `REQUIRED_DOCUMENT_MISSING`
- Profile: `PROFILE_INCOMPLETE`, `SENSITIVE_VALUE_UNKNOWN`
- Infrastructure: `APPLICATION_URL_MISSING`, `PLATFORM_UNSUPPORTED`
- Identity: `COMPANY_MISMATCH`, `TITLE_MISMATCH`, `URL_MISMATCH`
- Execution: `CAPTCHA_DETECTED`, `AUTH_REQUIRED`

**PreflightResult** dataclass:
- `eligible` — can proceed with execution
- `has_blockers` — hard stop (17 blocker reason codes)
- `needs_review` — requires human review (5 review codes)
- `checked_at` — ISO timestamp of validation

**Validation functions**:
| Function | Input | Output |
|---|---|---|
| `detect_listing_availability(text, http_status)` | Page text + HTTP status | `JobAvailability` |
| `check_deadline(deadline, expiring_soon_days)` | Date or datetime | `(valid, reason_code)` |
| `availability_from_freshness(status)` | FreshnessInfo status | `JobAvailability` |
| `validate_job_identity(...)` | Original vs current company/title/url | `(valid, mismatches)` |
| `validate_package(...)` | Package status, resume, quality gate | `(valid, issues)` |
| `validate_profile(profile_data)` | Dict with name/email | `(valid, issues)` |
| `run_preflight_checks(...)` | All job/package/profile data | `PreflightResult` |

### `app/services/queue_service.py` — Integration

Updated `run_preflight()` to:
1. Use `detect_listing_availability()` for job state
2. Use `availability_from_freshness()` to map freshness to availability
3. Call `check_duplicate()` from Phase 19 for duplicate detection
4. Call `run_preflight_checks()` for composite validation
5. Merge Phase 20 reason codes into existing attention logic

### Mock Server Scenarios

4 new routes added to `tests/e2e/mock_app_server.py`:
- `/job-active` — active listing with form
- `/job-closed` — "position filled" page
- `/job-removed` — 404 page
- `/job-expired-deadline` — expired listing

---

## Test Coverage (72 tests)

| Category | Count | Tests |
|---|---|---|
| JobAvailability model | 2 | Enum values, ReasonCode values |
| Listing detection | 11 | Active, closed, removed (404/410), unavailable (403), unknown (500), text patterns |
| Deadline handling | 8 | No deadline, future, past, today, expiring soon, datetime variants |
| Freshness mapping | 6 | All 6 freshness levels → availability |
| Job identity | 8 | Same, company mismatch, title mismatch, both, case insensitive, whitespace, no original, URL change |
| Package validation | 7 | Valid, missing, not approved, quality gate, missing resume, resume not found, not ready |
| Profile validation | 6 | Valid, missing, missing name, missing email, empty name, whitespace name |
| PreflightResult | 14 | All pass, expired/closed/removed blocks, unknown review, company mismatch, duplicate, missing package/resume, profile, deadline, expiring soon, CAPTCHA, timestamp, multiple failures |
| Playwright E2E | 8 | Active/closed/removed/expired job detection, preflight pass/block, CAPTCHA still blocks, auth still blocks |

---

## Safety Audit

| Check | Status |
|---|---|
| No CAPTCHA bypass | ✅ CAPTCHA detection returns BLOCK |
| No auth bypass | ✅ Login detection returns BLOCK |
| No credential exposure | ✅ No logging of credentials |
| No unsolicited communication | ✅ No recruiter messages |
| Human approval preserved | ✅ ambiguous/high-risk still ASK |
| No database migration needed | ✅ |
| No queue state conflicts | ✅ |

---

## Regression

| Suite | Result |
|---|---|
| Phase 15 (auth) | 131 pass |
| Phase 16 (advanced fields) | 128 pass |
| Phase 17 (E2E integration) | 55 pass |
| Phase 18 (Playwright E2E) | 48 pass |
| Phase 19 (submission verify) | 65 pass |
| **Phase 20 (preflight)** | **72 pass** |
| **Total** | **500 pass** |

---

## Architecture

```
Queue Service (run_preflight)
  └─ Job existence check
  └─ Application existence check
  └─ Package status check
  └─ URL/platform detection
  └─ Profile/resume check
  └─ Existing execution check
  └─ Answer validation check
  └─ Execution mode check
  └─ Freshness → Availability mapping (Phase 20)
  └─ Duplicate detection via Phase 19 (Phase 20)
  └─ Composite preflight checks (Phase 20)
       ├─ Availability state
       ├─ Deadline validation
       ├─ Job identity validation
       ├─ Package readiness
       ├─ Profile completeness
       ├─ CAPTCHA/Auth detection
       └─ → PreflightResult (eligible/blocked/review)
```

---

## Known Limitations

1. **Listing detection** is text-based heuristics — cannot detect all edge cases
2. **Identity validation** uses simple string comparison — no fuzzy matching
3. **Duplicate detection** relies on existing Application records — no cross-user dedup
4. **Deadline validation** only checks `application_deadline` field — no scraping of deadline text from listing
