# Phase 23 — Platform Capability Registry + Site Adapters

## Status: COMPLETE ✅

**Date:** 2026-09-10
**Tests:** 87 (Phase 23 only) | 822 total (Phases 15–23)
**No DB migration required** — capabilities are in-memory/static.

---

## 1. What was implemented

Phase 23 introduces a **platform capability registry** that stores what each job platform can and cannot do, plus an **execution planner** that decides whether the executor should attempt full automation, guide through unknowns, or defer to a human.

### Core module: `platform_capabilities.py`

| Component | Purpose |
|---|---|
| `CapabilityState` | SUPPORTED / PARTIAL / UNSUPPORTED / UNKNOWN / BLOCKED |
| `SubmissionCapability` | SUPPORTED / PARTIAL / UNSUPPORTED / UNKNOWN |
| `ExecutionStrategy` | FULL_AUTOMATIC / GUIDED_AUTOMATIC / HUMAN_ASSISTED / REVIEW_REQUIRED / BLOCKED |
| `PlatformCapability` | Full profile: form fields, documents, auth, submission, versioning |
| `PlatformCapabilityRegistry` | Singleton registry with defaults for 6 platforms |
| `RuntimeCapabilityObservation` | Discover capabilities at runtime for unknown platforms |
| `ExecutionPlan` | Strategy + blockers + warnings + confidence |
| `evaluate_capability_match` | Check required capabilities against platform profile |
| `determine_strategy` | Decide strategy from capability assessment |
| `generate_execution_plan` | Top-level planner |
| `discover_capabilities_from_observation` | Convert browser observation to capability profile |
| `decide_platform_support` | Plan → READY / REVIEW / BLOCKED decision |

### Default platform profiles

| Platform | Multi-page | File upload | Submission | Key limitation |
|---|---|---|---|---|
| generic | PARTIAL | SUPPORTED | UNKNOWN | Must verify before auto-submit |
| linkedin | SUPPORTED | SUPPORTED | SUPPORTED | Easy Apply only |
| indeed | SUPPORTED | SUPPORTED | PARTIAL | External redirects |
| naukri | PARTIAL | SUPPORTED | PARTIAL | Limited autocomplete |
| company_career | PARTIAL | SUPPORTED | UNKNOWN | Varies by ATS |
| human_assisted | SUPPORTED | SUPPORTED | UNSUPPORTED | No automated submission |

### Executor integration

Added `capability_check` step between `resolve_policy` and `preflight_check`:

1. `generate_execution_plan()` evaluates platform capabilities
2. If BLOCKED → record blockers, set status, return early
3. If REVIEW/other → record warnings, continue execution

---

## 2. Safety rules enforced

| Rule | Enforcement |
|---|---|
| Never bypass CAPTCHA | CAPTCHA → BLOCKED (strategy = BLOCKED) |
| Never bypass authentication | LOGIN_REQUIRED/MFA_REQUIRED → HUMAN_ASSISTED |
| Auth terminal states | AUTH_FAILED/SESSION_EXPIRED/BLOCKED → BLOCKED |
| No credential scraping | Not implemented — detection only |
| No session token extraction | Not implemented — detection only |
| No hostname conditionals | All planning is capability-based |
| Unknown platforms → REVIEW | Generic fallback requires submission verification |
| Missing required capabilities → BLOCKED | Non-submission capabilities block execution |
| Partial submission → REVIEW | Submission capability PARTIAL requires verification |
| Human-assisted remains safe | UNSUPPORTED submission → HUMAN_ASSISTED strategy |

---

## 3. Test coverage (87 tests)

| Category | Tests |
|---|---|
| Capability states & enums | 6 |
| Registry singleton & lookup | 8 |
| Capability matching | 5 |
| Generic fallback | 3 |
| Platform adapters & quirks | 5 |
| Field capability matrix | 3 |
| Document capability matrix | 2 |
| Auth capability matrix | 3 |
| Submission capability | 3 |
| Execution plans | 11 |
| Support decisions | 4 |
| Platform support rules | 7 |
| Capability discovery | 5 |
| Platform safety gate | 4 |
| Capability versioning | 5 |
| Capability map | 2 |
| Queue integration | 2 |
| Safety verification | 9 |

---

## 4. Regression

```
Phase 15:  131 tests ✅
Phase 16:  128 tests ✅
Phase 17:   55 tests ✅
Phase 18:   48 tests ✅
Phase 19:   65 tests ✅
Phase 20:   72 tests ✅
Phase 21:  110 tests ✅
Phase 22:  126 tests ✅
Phase 23:   87 tests ✅
─────────────────────
Total:     822 tests ✅
```

---

## 5. Files created/modified

| File | Action |
|---|---|
| `app/application_execution/platform_capabilities.py` | **CREATED** — 820 lines |
| `app/application_execution/executor.py` | **MODIFIED** — capability_check step + STEP_ORDER update |
| `tests/test_phase23_platform_capabilities.py` | **CREATED** — 87 tests |

---

## 6. What this phase does NOT do

- Does not change database schema
- Does not modify mock_app_server.py (capabilities are in-memory)
- Does not bypass preflight or readiness checks
- Does not add real browser capability detection (deferred to runtime)
- Does not commit changes (awaiting explicit instruction)

---

## Next phase (Phase 24)

Runtime platform capability discovery — inspect actual form pages to update capability profiles dynamically.
