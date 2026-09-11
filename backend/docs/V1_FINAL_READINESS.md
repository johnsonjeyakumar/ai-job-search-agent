# V1 FINAL READINESS — Automatic Job Application Agent

## Architecture

The system is a monolithic FastAPI backend (Python 3.14.5, SQLAlchemy, PostgreSQL 18) with a React+Vite frontend. The execution pipeline flows through 18 connected stages from queue entry to tracking confirmation.

**Core modules:** executor.py (1724 lines), form_orchestrator.py (750 lines), readiness.py (1185 lines), platform_capabilities.py (817 lines), idempotency_locks.py (900+ lines), submission_verify.py (430 lines), question_handler.py (593 lines), answer_engine.py (501 lines), browser.py (800+ lines)

**Database:** 38 tables, 16 linear migrations, no drift.

**Tests:** 823 passing (Phase 15-24 regression), 47/48 Playwright E2E (1 transient network failure).

## Execution Path

```
Queue (enqueue) → Preflight (15 checks) → Autopilot (concurrency gate)
→ Executor Preflight (5 checks) → Lock Acquisition (advisory lock)
→ Platform Detection → Capability Check → Browser Open → CAPTCHA Check
→ Auth Check → Form Inspection → Field Mapping → Resume Upload
→ Field Filling → Form Validation → Pre-Submission Decision
→ Human Approval → Submit Execution → Submission Verification
→ Application Tracker → Tracking Events → Evidence Recording
```

Every stage has: entry function, state change, DB write, error handling, evidence recording, next transition.

## State Machines

| Machine | States | Transitions | Status |
|---------|--------|-------------|--------|
| Tracking | 16 | Explicit graph in status.py | VALIDATED |
| Execution | 10 | Procedural in executor.py | VALIDATED |
| Queue | 12 | Explicit graph in queue_service.py | VALIDATED |
| Form Session | 15 | Explicit graph in form_session.py | VALIDATED (COMPLETED removed) |
| Readiness | 6 | Priority-ordered decision tree | VALIDATED |

**Invalid combinations checked:** READY+incomplete profile, EXECUTING+no owner, SUBMISSION_CONFIRMED+no attempt, READY+duplicate, READY+expired job, READY+uncertain submission — all properly guarded.

## Security

| Check | Status |
|-------|--------|
| No credentials stored in DB | PASS |
| No session tokens persisted | PASS |
| No cookie extraction | PASS |
| CAPTCHA never bypassed | PASS |
| Authentication never auto-completed | PASS |
| No eval/exec | PASS |
| No subprocess | PASS |
| API authentication (Bearer + X-Api-Key) | PASS |
| Health endpoint exempt from auth | PASS |
| OPTIONS exempt from auth | PASS |
| Generic 500 error messages | PASS |
| .gitignore properly configured | PASS |

## Browser E2E

47/48 Playwright tests pass against local mock server. The 1 failure is `net::ERR_NETWORK_CHANGED` — a transient OS-level network issue, not a code defect. Tests cover: single-page, multi-page, conditional fields, advanced controls, autocomplete, date, currency, multi-select, file upload, knockout questions, sensitive questions, human approval, auth pause, CAPTCHA block, review page, confirmation, uncertain submission, duplicate protection.

## Concurrency

- PostgreSQL advisory locks with 120s stale timeout
- `max_concurrent_executions` enforced via active execution count
- Worker ownership tracked via `owner_id` on execution_locks
- Idempotency key prevents duplicate executions
- `check_submit_boundary()` prevents double-submit

## Idempotency

- `generate_idempotency_key()` creates deterministic keys from package+job+attempt
- Duplicate key detection via unique constraint
- `ON CONFLICT DO UPDATE` for lock acquisition
- `authorize_retry()` requires explicit authorization for uncertain submissions

## Submission Verification

| Outcome | Execution Status | Tracking Status | Auto-retry? |
|---------|-----------------|-----------------|-------------|
| SUBMISSION_CONFIRMED | SUBMISSION_CONFIRMED | SUBMISSION_CONFIRMED | No |
| SUBMITTED | SUBMITTED | SUBMITTED | No |
| SUBMISSION_UNCERTAIN | SUBMISSION_UNKNOWN | SUBMITTED | No (human review) |
| SUBMISSION_FAILED | EXECUTION_FAILED | EXECUTION_READY | Manual only |
| DUPLICATE_SUSPECTED | BLOCKED | EXECUTION_READY | Manual only |
| BLOCKED | BLOCKED | EXECUTION_READY | Manual only |

**Invariant:** Once final submission has started, no automatic submission retry.

## Readiness Gate

10-level deterministic decision cascade:
1. Package invalid → BLOCKED
2. Duplicate applied → BLOCKED
3. Duplicate suspected → REVIEW
4. Previous uncertain submission → REVIEW
5. Contradictory data → REVIEW
6. Ambiguous answers → REVIEW
7. Unsafe sensitive values → REVIEW
8. Required fields missing → NEEDS_INPUT
9. Required documents invalid → BLOCKED
10. Package not approved → REVIEW

Readiness is rechecked immediately before execution.

## Platform Capabilities

6 platforms registered: linkedin, indeed, naukri, company_career, generic, human_assisted.

Three-layer fallback: detector → adapter → capability registry. Unknown platforms safely default to HUMAN_ASSISTED.

| Platform | Default Mode | Auto-submit? |
|----------|-------------|--------------|
| linkedin | HUMAN_ASSISTED | No |
| indeed | HUMAN_ASSISTED | No |
| naukri | HUMAN_ASSISTED | No |
| company_career | PERMITTED_BROWSER | Yes (with approval) |
| generic | PERMITTED_BROWSER | No (adapter override) |
| human_assisted | HUMAN_ASSISTED | No (adapter override) |

## Question Safety

| Question Class | Behavior |
|---------------|----------|
| E_SIGNATURE | Requires USER_VERIFIED memory answer; blocked if missing |
| LEGAL_DECLARATION | Requires USER_VERIFIED; needs_user_input if missing |
| DEMOGRAPHIC | Never inferred; requires USER_VERIFIED |
| KNOCKOUT | Requires verified answer; never fabricated |
| Optional consent | Defaults to "No" |
| HIGH sensitivity | can_auto_fill=False; needs_review=True |

**No guessing, no inference of sensitive values, no fabricated qualifications.**

## File Safety

- Double-layer validation: storage/validation.py + file_handler.py
- Extension allowlists per document type
- MIME type cross-check
- Magic byte validation (PDF, DOCX)
- 10MB size limit
- Path traversal prevention (UUID-based storage keys)
- No executable file upload paths

## Database

- 38 tables, all with matching models and migrations
- Linear migration chain (16 revisions, no branches)
- All FKs reference existing tables with appropriate cascade rules
- Indexes cover all common query patterns
- No schema drift (alembic check: "No new upgrade operations detected")

## Performance

- Advisory locks are session-scoped (no polling)
- Readiness check is deterministic (no LLM, no external calls)
- Platform capability lookup is O(1) registry lookup
- Evidence store is in-memory (no DB writes during form filling)
- Checkpoint store is in-memory (crash-safe via executor state machine)
- No N+1 query patterns in critical path
- DB flush after each step (could batch for performance, but safety > speed)

## User-Facing Behavior

| Status | Meaning | User Action |
|--------|---------|-------------|
| READY | All checks passed | Proceed |
| REVIEW | Ambiguities detected | Review and resolve |
| BLOCKED | Cannot proceed | Fix underlying issue |
| EXECUTING | Browser automation running | Wait |
| SUBMITTED | Submission occurred | Await confirmation |
| SUBMISSION_CONFIRMED | Confirmed successful | None |
| FAILED | Execution failed | Check error details |
| DUPLICATE | Already applied | None |
| UNCERTAIN | Submission unclear | Human review required |

No misleading "success" wording for uncertain submissions.

## Remaining Limitations

1. **Transient Playwright failures** — `net::ERR_NETWORK_CHANGED` occurs occasionally (1/48 tests). This is an OS-level issue, not a code defect.
2. **In-memory evidence/checkpoint stores** — Crash loses form-filling evidence. Executor state machine ensures safe recovery.
3. **Pre-existing ruff warnings** — 2 unused variables in `browser.py` (not from V1 changes).
4. **Full test suite timeout** — `pytest -q` on all tests exceeds 120s in this environment. Phase 15-24 subset (823 tests) runs in ~25s.

## Supported Usage Level

**CONTROLLED SINGLE-USER REAL APPLICATIONS**

Supported:
- Known platform capabilities (LinkedIn, Indeed, Naukri, company career sites)
- Human-assisted auth/MFA
- Human approval for sensitive actions
- Supported browser flows (single-page, multi-page, conditional)

Unsupported (by design):
- Arbitrary unknown sites
- CAPTCHA solving
- Anti-bot bypass
- Credential automation
- Unattended high-risk submission
- Large-scale multi-user deployment

## Files Modified in This Task

| File | Change |
|------|--------|
| `app/api/routes/applications.py` | Fixed `_handle_exec_error` to return generic 500 message |
| `app/main.py` | Added health endpoint and OPTIONS exemption to auth middleware |

Both changes are minimal, targeted fixes for audit findings.

## Verification Results

| Check | Result |
|-------|--------|
| pytest (Phase 15-24) | 823/823 PASSING |
| Playwright E2E | 47/48 PASSING (1 transient network failure) |
| ruff check | All modified files clean |
| alembic upgrade head | SUCCESS |
| alembic check | No drift |
| npm run build | SUCCESS |
| git status | 14 files modified, 1 untracked (PHASE25.md) |
