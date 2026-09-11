# Phase 24 — Idempotency + Execution Locks + Reliability Hardening

**Date:** 2026-09-10
**Tests:** 49 new tests, all passing
**Regression:** 180 tests (Phase 15 + 24) passing; all individual Phase 15-24 test files passing

## What Was Built

### Core Module: `idempotency_locks.py` (929 lines)

Central safety guarantee: ONE APPLICATION → ONE ACTIVE EXECUTOR → ONE CONTROLLED SUBMISSION ATTEMPT → NO ACCIDENTAL DUPLICATE SUBMISSION

#### ExecutionLockManager (PostgreSQL-backed)
- **Acquire**: Uses `pg_try_advisory_lock()` for cross-process safe locking. Returns `ACQUIRED`, `ALREADY_LOCKED`, `STALE_LOCK_RELEASED`, or `ERROR`.
- **Release**: Explicitly releases the PG advisory lock and marks the ownership row as released.
- **Heartbeat**: Updates the heartbeat timestamp to prevent stale lock detection during long operations.
- **Stale Detection**: Compares `heartbeat_at` (or `lock_acquired_at`) against `STALE_LOCK_TIMEOUT_SECONDS` (120s).

#### Submit Boundary
- `mark_submit_attempted()`: Records when a final submission action was attempted.
- `check_submit_boundary()`: Prevents duplicate submissions by checking execution status.
- States that block re-submission: `SUBMITTED`, `SUBMISSION_CONFIRMED`, `SUBMISSION_UNKNOWN`.

#### Retry Authorization
- `authorize_retry()`: Only allowed for `SUBMISSION_UNKNOWN` status. Sets `retry_authorized_at` and `retry_reason`.
- `is_retry_authorized()`: Checks if retry authorization exists.

#### Crash Recovery
- `assess_crash_recovery()`: Determines recovery action based on execution state:
  - `RESUME_SAFE`: Pre-submit crash, safe to resume
  - `VERIFY_OUTCOME`: Post-submission crash, verify outcome first
  - `HUMAN_REVIEW`: Uncertain states require human review
  - `NO_ACTION`: Terminal states

#### Queue Idempotency
- `check_queue_duplicate()`: Detects duplicate queue items for the same job. Checks both active queue items and prior submission history.

#### Execution Consistency
- `check_execution_consistency()`: Validates execution state consistency:
  - `SUBMISSION_CONFIRMED` without submit attempt
  - `EXECUTING` with no lock owner

#### Idempotency Keys
- `generate_idempotency_key()`: Deterministic key from `package_id + job_id + attempt_number`.
- `parse_idempotency_key()`: Reverse parsing for validation.

### Database Migration (`4fe428962347`)

1. **`execution_locks` table**:
   - `package_id` (unique indexed)
   - `execution_id` (nullable)
   - `owner_id` (indexed)
   - `lock_acquired_at`, `heartbeat_at`, `released_at`

2. **`application_executions` new columns**:
   - `idempotency_key` (unique indexed)
   - `submission_attempted_at`
   - `retry_authorized_at`
   - `retry_reason`

### Executor Integration

- Lock acquisition at start of `run_execution()` before any browser operations
- Heartbeat updates after browser open and form inspection
- Lock release on error/exception paths
- Submit boundary check in `submit_execution()` before final submit
- Idempotency key set on execution record

### SQLAlchemy Model: `ExecutionLock`

Added `ExecutionLock` model to `app/models/application_execution.py` so `Base.metadata.create_all()` in tests creates the `execution_locks` table (previously only created via Alembic migration).

## Test Coverage (49 tests)

### Test Classes
- `TestIdempotencyKeyGeneration`: Key generation and parsing (6 tests)
- `TestExecutionLockManager`: Lock acquisition, release, heartbeat, owner tracking (9 tests)
- `TestStaleLockRecovery`: Stale detection, heartbeat info (3 tests)
- `TestSubmitBoundary`: Pre/post submit state checks (7 tests)
- `TestRetryAuthorization`: Retry auth for uncertain submissions (3 tests)
- `TestCrashRecovery`: Recovery assessment for all states (9 tests)
- `TestQueueIdempotency`: Duplicate queue detection (4 tests)
- `TestExecutionConsistency`: State consistency checks (3 tests)
- `TestSafetyVerification`: Safety property validation (5 tests)

### Key Test Patterns
- Separate DB connections for lock contention tests (PG session-level advisory locks are reentrant within same session)
- `execution_factory` fixture creates parent rows (profiles, jobs, packages) to satisfy FK constraints
- Stale lock simulation: acquire in separate connection, make stale, explicitly release PG advisory lock

## Safety Properties Verified
1. Same package cannot be concurrently executed by two workers
2. Different packages are independent
3. Post-submit no auto-retry
4. Uncertain submissions require human review
5. Crash recovery prefers safe-resume or human-review over auto-retry
