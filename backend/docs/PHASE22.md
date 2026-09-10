# Phase 22 — Application Profile Completeness + Readiness Gate

## Summary
Phase 22 implements a deterministic Application Readiness Gate that runs BEFORE an application enters automatic browser execution. The system answers: "Do we have everything required to safely and truthfully apply for this specific job?"

## Readiness Flow
```
JOB QUALIFIES → PROFILE CHECK → REQUIRED ANSWERS CHECK
→ REQUIRED DOCUMENT CHECK → APPLICATION PACKAGE CHECK
→ PREFLIGHT CHECK → DUPLICATE CHECK → AUTH READINESS
→ READINESS DECISION → AUTOPILOT / REVIEW / BLOCK
```

## What Was Built

### Readiness Module (`readiness.py`)

**ReadinessStatus enum** (6 values):
- `READY` — All checks pass, safe to execute
- `NEEDS_INPUT` — Required data missing, must get from user
- `REVIEW` — Ambiguous/contradictory/sensitive, needs human review
- `BLOCKED` — Cannot proceed (expired, duplicate, invalid package)
- `INCOMPLETE` — Profile/data insufficient
- `INVALID` — Package or documents invalid

**RequirementCategory enum** (18 categories):
`IDENTITY`, `CONTACT`, `LOCATION`, `EDUCATION`, `EXPERIENCE`, `SKILLS`, `WORK_AUTHORIZATION`, `SPONSORSHIP`, `AVAILABILITY`, `COMPENSATION`, `RELOCATION`, `DOCUMENT`, `PORTFOLIO`, `LINK`, `DECLARATION`, `SIGNATURE`, `CONSENT`, `SENSITIVE`, `CUSTOM`

**RequirementStatus enum** (8 statuses):
`SATISFIED`, `MISSING`, `AMBIGUOUS`, `CONTRADICTORY`, `UNSAFE`, `NOT_APPLICABLE`, `INVALID`, `UNVERIFIED`

**Key functions:**
- `evaluate_profile_completeness()` — Informational score, does NOT determine readiness
- `detect_requirements_from_form_fields()` — Application-specific requirement detection from form fields and job data
- `check_answer_readiness()` — 3-source priority: profile → application answers → memory
- `check_document_readiness()` — Resume, cover letter, generic document validation
- `detect_profile_conflicts()` — Profile vs application answer contradiction detection
- `check_previous_execution_blockers()` — SUBMISSION_UNKNOWN/BLOCKED history blocks
- `check_package_readiness()` — Package status/quality_gate/readiness validation
- `determine_readiness()` — 11-step deterministic decision rules
- `run_readiness_check()` — Main entry point combining all checks
- `needs_refresh()` — Staleness detection (default 30 minutes)

### Queue Integration (`queue_service.py`)

The readiness gate is integrated as step 14 in `run_preflight()`. It runs after all Phase 20 preflight checks and applies its own decision layer:

- `BLOCKED` → `ATTENTION_BLOCK`
- `INVALID` → `ATTENTION_BLOCK`
- `NEEDS_INPUT` → `ATTENTION_ASK`
- `REVIEW` → `ATTENTION_REVIEW`
- `INCOMPLETE` → `ATTENTION_ASK`
- `READY` → keeps current attention (never downgrades from BLOCK/REVIEW)

### Deterministic Decision Rules

1. Package invalid → BLOCKED
2. Duplicate already applied → BLOCKED
3. Duplicate suspected → REVIEW
4. Previous execution uncertain → REVIEW
5. Contradictory data → REVIEW
6. Ambiguous answers → REVIEW
7. Unsafe sensitive values → REVIEW
8. Missing required fields → NEEDS_INPUT
9. Required documents invalid → BLOCKED
10. Package not approved → REVIEW
11. All checks pass → READY

### Mock Server Scenarios (15 new routes)
- `/ready/basic` — Basic application form
- `/ready/missing-phone` — Missing phone field
- `/ready/missing-resume` — Resume required
- `/ready/cover-letter-required` — Cover letter required
- `/ready/portfolio-required` — Portfolio URL required
- `/ready/sponsorship-required` — Sponsorship question
- `/ready/work-auth-required` — Work authorization question
- `/ready/sensitive-question` — Gender/demographic question
- `/ready/contradictory` — City field for conflict detection
- `/ready/duplicate` — Duplicate application
- `/ready/expired-job` — Closed/expired job
- `/ready/invalid-package` — Invalid package status
- `/ready/unresolved-approval` — Needs approval
- `/ready/previous-uncertain` — Previous uncertain submission
- `/ready/fully-ready` — All requirements met

## Safety Rules Enforced
1. Never fabricate applicant information
2. Never infer sensitive information from unrelated data
3. Never modify profile facts automatically
4. Never silently mutate resumes or packages
5. Never create fake answers to make an application READY
6. Human review required for ambiguous, sensitive, or unknown requirements
7. Contradictory sources require review
8. Missing required documents block or review
9. Unverified documents cannot become READY
10. Expired jobs cannot become READY
11. Duplicates cannot become READY
12. Uncertain submissions cannot become READY
13. Autopilot cannot bypass readiness gate
14. Readiness is rechecked before execution (staleness detection)

## Test Results
- **126 tests pass** in Phase 22 test suite
- **736 tests pass** across Phases 15-22 (full regression)
- **0 failures**

## Database
- No migration required — readiness is calculated dynamically, not stored
- `alembic check` confirms no new upgrade operations needed

## Files Created/Modified
- `app/application_execution/readiness.py` — **NEW**: Core readiness gate module
- `app/services/queue_service.py` — **UPDATED**: Phase 22 readiness gate integration
- `tests/e2e/mock_app_server.py` — **UPDATED**: 15 new mock scenarios
- `tests/test_phase22_readiness.py` — **NEW**: 126 tests
