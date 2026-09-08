# Phase 12: Advanced Application Automation Engine

## Overview

Phase 12 transforms the application execution engine into an intelligent, resilient system that knows when to act, ask, refuse, retry, and stop. The engine now features semantic field mapping, application memory, question handling, form validation, human approval boundaries, browser resilience, checkpointing, idempotency, analytics, and security controls.

## Core Principles

1. **DO NOT automate blindly** — The agent knows when to act, ask, refuse, retry, stop
2. **Evidence-bound answers** — AI may only rephrase verified facts, never invent
3. **Human approval boundaries** — Stop for submission, CAPTCHAs, high-sensitivity fields
4. **Browser resilience** — Recover from disconnections, timeouts, transient errors
5. **Idempotency** — Operations can be safely retried without side effects
6. **Security** — Mask sensitive data, classify fields, enforce privacy

## New Components

### 1. Field Catalog (`field_catalog.py`)

Canonical field concepts with aliases, sensitivity levels, and validation rules.

**Field Categories:**
- `PERSONAL` — Name, email, phone, location, social URLs
- `WORK` — Company, experience, role, notice period, salary
- `EDUCATION` — Degree, university, graduation year
- `AUTHORIZATION` — Work authorization, sponsorship
- `APPLICATION` — Cover letter, availability, relocation
- `FILES` — Resume, cover letter, portfolio uploads

**Sensitivity Levels:**
- `LOW` — Safe for auto-fill (name, email, location)
- `MEDIUM` — Requires user confirmation (salary, current company)
- `HIGH` — Requires explicit user verification (authorization, sponsorship)

### 2. Semantic Mapper (`semantic_mapper.py`)

Multi-strategy field mapping:
1. **Deterministic** — Exact label match (HIGH confidence)
2. **Alias** — Alias lookup (HIGH confidence)
3. **Token containment** — Partial token match (MEDIUM confidence)
4. **Semantic** — Word similarity (MEDIUM/LOW confidence)
5. **User-verified** — Custom mappings (HIGH confidence)

### 3. Application Memory (`memory.py`)

Stores verified answers for reuse across submissions:
- `USER_VERIFIED` — Explicitly verified by user (safe for sensitive fields)
- `SYSTEM_DERIVED` — Computed from profile data
- `UNVERIFIED` — Not yet verified

**Memory Features:**
- Answer normalization (question text → canonical form)
- Verification status tracking
- Usage analytics
- Unknown question recording

### 4. Question Handler (`question_handler.py`)

Classifies and handles application questions:
- **Known concepts** — Authorization, sponsorship, salary questions
- **Category classification** — Authorization, salary, experience, etc.
- **Sensitivity detection** — Identifies sensitive questions
- **Answer type detection** — Text, select, boolean

### 5. Answer Engine (`answer_engine.py`)

Generates evidence-bound answers:
- Profile data matching (exact, derived, content-based)
- Memory lookup (verified, unverified)
- Evidence binding (every answer has a source)
- Review requirements (medium/high sensitivity)

### 6. Mapping Pipeline (`pipeline.py`)

Full 8-stage pipeline:
1. **INSPECT** — Extract raw field data
2. **EXTRACT** — Parse label text
3. **NORMALIZE** — Normalize label format
4. **MATCH** — Map to canonical concept
5. **LOOKUP** — Find values in profile/memory
6. **CALCULATE** — Compute derived values
7. **APPLY** — Determine fill method (auto/manual/skip)
8. **VALIDATE** — Check required, type, consistency

### 7. Checkpointing (`checkpoint.py`)

Saves execution state at every critical step:
- Form inspected
- Fields mapped
- Fields filled
- Questions answered
- Submission attempted/confirmed/failed
- Human approval requested/granted
- Error recovery

**Resume capability:**
- Can resume from any checkpoint
- Replaying checkpoints produces same result
- Integrity verification via data hashing

### 8. Resilience (`resilience.py`)

Browser disconnection handling:
- Automatic recovery attempts
- Page state validation
- Retry with exponential backoff
- Idempotency keys for safe retries

### 9. Human Approval (`human_approval.py`)

Defines when the agent MUST stop:
- **Submit application** — Always requires approval
- **Handle CAPTCHA** — Always requires approval
- **High-sensitivity fields** — Requires explicit verification
- **Abort application** — Always requires approval

### 10. Evidence Tracker (`evidence_tracker.py`)

Records evidence for every action:
- Field fills (before/after values, source, confidence)
- Question answers
- Submission attempts
- Errors and recoveries

**Evidence properties:**
- Immutable (cannot be modified after creation)
- Integrity-verified (SHA-256 hashing)
- Audit-logged

### 11. Analytics (`analytics.py`)

Tracks execution metrics:
- Mapping accuracy by field type
- Fill rate by platform
- Question answer rate
- Submission success rate
- Human approval frequency

### 12. Security (`security.py`)

Security controls:
- **Field classification** — PUBLIC, INTERNAL, PERSONAL, FINANCIAL, AUTHORIZATION
- **Auto-fill restrictions** — Only allowed for PUBLIC/INTERNAL/PERSONAL
- **Value masking** — Sensitive values masked in logs
- **Input validation** — Email, phone, URL, year formats

## API Endpoints

### Field Catalog
- `GET /api/v1/execution/catalog` — Get complete field catalog
- `GET /api/v1/execution/catalog/{canonical}` — Get specific field concept

### Semantic Mapping
- `POST /api/v1/execution/map-fields` — Map detected fields to canonical concepts

### Application Memory
- `POST /api/v1/execution/memory/answers` — Add/update verified answer
- `GET /api/v1/execution/memory/answers` — List answers with filters
- `POST /api/v1/execution/memory/answers/{question}/verify` — Mark as verified
- `POST /api/v1/execution/memory/answers/{question}/revoke` — Revoke answer

### Unknown Questions
- `POST /api/v1/execution/memory/unknown-questions` — Record unknown question
- `POST /api/v1/execution/memory/unknown-questions/{question}/resolve` — Resolve with answer

### Question Handling
- `POST /api/v1/execution/handle-question` — Handle application question

### Checkpoints
- `GET /api/v1/execution/checkpoints/{run_id}` — Get checkpoints and resume point

### Human Approval
- `POST /api/v1/execution/approval/request` — Request approval
- `POST /api/v1/execution/approval/{run_id}/{action}/grant` — Grant approval
- `POST /api/v1/execution/approval/{run_id}/{action}/deny` — Deny approval

### Analytics
- `GET /api/v1/execution/analytics/overall` — Get overall statistics
- `GET /api/v1/execution/analytics/field-mapping` — Get field mapping accuracy
- `GET /api/v1/execution/analytics/platforms` — Get platform performance

### Security
- `GET /api/v1/execution/security/classification/{canonical}` — Get field classification
- `POST /api/v1/execution/security/check-auto-fill` — Check auto-fill permission

## Constraints

1. **DO NOT** bypass CAPTCHAs or anti-bot measures
2. **DO NOT** store raw passwords or session cookies insecurely
3. **DO NOT** submit without required human approval
4. **DO NOT** falsify answers or invent experience
5. Only `USER_VERIFIED` answers may auto-fill sensitive fields
6. All sensitive fields must follow explicit risk policy

## Tests

49 new tests covering:
- Field catalog lookup and indexing
- Semantic mapping accuracy
- Memory operations (add, verify, revoke, list)
- Question classification and handling
- Checkpoint creation and resume
- Human approval workflows
- Analytics tracking
- Security controls and validation
- Pipeline stages and contradiction detection

---

# Phase 13: Application Queue & Autopilot Orchestration

## Overview

Phase 13 adds the application processing queue and autopilot orchestration layer on top of the Phase 12 execution engine. The queue decides *which* approved packages to process and in *what order*, then delegates to the existing executor.

The autopilot is the core "automatic job application agent" — it batch-processes queued items with minimum human attention.

## Queue States (Orchestration Only)

Queue states never conflict with `TRACKING_STATUSES` or `EXECUTION_STATUSES`:

```
QUEUED -> PREPARING -> READY -> APPROVED -> EXECUTING -> SUBMITTED -> COMPLETED
         \-> NEEDS_INPUT    \-> REVIEW    \-> BLOCKED
                           \-> BLOCKED
```

## Attention Categories

Every queue item resolves to one of:
- **AUTO** — Process automatically (preflight passed, no blockers)
- **ASK** — Needs user input (missing resume, invalid answers)
- **REVIEW** — Needs human review (non-standard package)
- **BLOCK** — Cannot proceed (no URL, unsupported platform, duplicate submission)

## Priority Formula

```
priority = (match * 0.35) + (opportunity * 0.35) + (quality * 0.15) + (freshness * 0.15)
```

All weights are deterministic, documented, and auditable. No LLM involvement.

## Preflight Checks

1. Job exists
2. Application exists
3. Package status is APPROVED
4. Application URL is available
5. Platform is supported
6. User profile configured
7. Resume selected
8. No existing confirmed submission
9. No unresolved blocking conditions
10. Execution policy permits automation

## API Endpoints

- `GET /api/v1/queue` — List queue items (filter by state, attention)
- `GET /api/v1/queue/stats` — Queue statistics and daily limits
- `POST /api/v1/queue/enqueue` — Add approved package to queue
- `GET /api/v1/queue/{id}` — Get queue item details
- `POST /api/v1/queue/{id}/preflight` — Run preflight checks
- `POST /api/v1/queue/{id}/resolve` — Resolve NEEDS_INPUT item
- `POST /api/v1/queue/{id}/skip` — Skip queue item
- `POST /api/v1/queue/{id}/transition` — Manual state transition
- `POST /api/v1/queue/autopilot/start` — Start autopilot run
- `POST /api/v1/queue/autopilot/{id}/pause` — Pause run
- `POST /api/v1/queue/autopilot/{id}/resume` — Resume run
- `POST /api/v1/queue/autopilot/{id}/stop` — Stop run
- `GET /api/v1/queue/autopilot/status` — Get autopilot status

## Frontend

- `/application-queue` — Queue view with autopilot controls, filters, attention center

## Tests

38 new tests covering:
- Priority calculation and scoring
- Queue CRUD and state transitions
- Preflight check classification
- Autopilot run lifecycle (start/pause/resume/stop)
- Daily limit enforcement
- API endpoint responses
- Model persistence
