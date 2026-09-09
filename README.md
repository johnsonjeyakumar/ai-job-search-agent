# Job Search & Application Agent

A personal, **local-first** automatic job application agent: discovers jobs,
scores them, prepares tailored application packages, and executes safe,
human-gated application workflows against the platforms where jobs live.

**Primary product:** Automatic Job Application Agent

**Supporting features:** Interview preparation, skill gaps, learning, analytics,
follow-ups — secondary and minimal priority.

**Current status:** Phases 1–13 complete. Core application automation verified.
No automatic mass-application, and nothing is ever submitted without explicit
human approval.

## Implemented phases

| Phase | Scope | Status |
| ----- | ----- | ------ |
| 1 | Foundation — FastAPI + SQLAlchemy + Alembic backend, React + Vite + Tailwind frontend shell, DB integration, AI/job-source abstraction layers | ✅ |
| 2 | Profile / Preferences / Resumes — profile CRUD + onboarding, editable search preferences, resume upload / versioning / active-marking | ✅ |
| 3 | Job Discovery / Apify — source-agnostic `JobSource`, Apify Indeed adapter, normalization + dedupe, manual run via `POST /jobs/search`, `automation_runs` logging, jobs list UI with filters | ✅ |
| 4 | Job Intelligence — deterministic job-quality scoring (freshness, description, requirements, application, company, location, salary), explainable components, `GET /jobs/{id}/match` groundwork | ✅ |
| 5 | Personal Matching / Opportunity Scoring — deterministic matching (`job_matches`: skills, experience, role, location, education, remote, employment_type, salary, certifications), opportunity score, APPLY/REVIEW recommendations with evidence + blockers; strict AI output contract (the LLM can never emit scores) | ✅ |
| 6 | Application Preparation — tailored per-job application packages (quality gate, deterministic answers, cover letter drafts, answer editing), validate / approve / archive lifecycle, resume selection | ✅ |
| 7 | Platform-Aware Application Execution — detect platform → resolve per-platform policy → fill only known-safe fields → stop at the human approval boundary → record ordered step trail, evidence, and confirmation; mock + Playwright browser drivers; execution UI at `/applications/:id/execute` | ✅ |
| 8 | Application Tracking — immutable lifecycle + timeline (`/tracking/applications`), follow-up scheduling state, funnel + performance analytics APIs and dashboard widgets | ✅ |
| 9 | Follow-Up Engine + Analytics — typed priorities/reasons/trigger-keys, skip/restore/cancel/reschedule actions, interview thank-you scheduling; resume performance + recommended resume, source quality (discovery + submission), response-time breakdowns, deterministic insights; `/analytics` page | ✅ |
| 10 | Interview Preparation — interview workspace, question bank, round management, thank-you notes | ✅ |
| 11 | Skill Gaps & Learning — skill gap analysis, learning plan generation, resource management, demand signals | ✅ |
| 12 | Advanced Application Automation Engine — semantic field mapping (31 canonical concepts), application memory with verified answer reuse, question classification and handling, evidence-bound answer generation (never invents facts), 8-stage mapping pipeline, execution checkpointing and resume, browser resilience with bounded retry, human approval boundaries, idempotency for safe retries, execution evidence tracking with SHA-256 integrity, security controls and field classification, 18 API endpoints, 532 tests | ✅ |
| 12.1 | QA Fixes — answer engine bug fix, ruff cleanup, backend restart, regression verification | ✅ |
| 13 | Application Queue & Autopilot Orchestration — processing queue with deterministic priority scoring, attention classification (AUTO/ASK/REVIEW/BLOCK), preflight checks, autopilot batch processing, daily limits, 14 API endpoints, frontend queue page, 38 new tests | ✅ |

## Application automation workflow

```
JOB DISCOVERY
→ MATCHING
→ APPLICATION PREPARATION
→ APPLICATION QUEUE (priority-scored, attention-classified)
→ AUTOPILOT (batch processing, daily limits)
→ FORM INSPECTION
→ FIELD MAPPING (semantic, alias, token, user-verified)
→ APPLICATION MEMORY (verified answer reuse)
→ QUESTION HANDLING (classify, detect sensitivity)
→ ANSWER ENGINE (evidence-bound, never invents)
→ VALIDATION (required fields, format checks)
→ HUMAN APPROVAL (required for submission, CAPTCHA, high-sensitivity)
→ BROWSER EXECUTION (bounded retry, checkpoint recovery)
→ SUBMISSION
→ CONFIRMATION (observable state, not just click)
→ TRACKING (immutable lifecycle, follow-ups)
```

## Safety / execution model

- **Human approval gate:** every submission requires explicit human approval.
  CAPTCHA, high-sensitivity fields, and destructive actions always require approval.
- **Evidence-bound answers:** AI may only reword verified facts. Never invents
  experience, qualifications, or application answers.
- **No CAPTCHA / anti-bot bypass:** CAPTCHA detection stops execution.
- **No credential bypass:** no passwords, cookies, or session data collected or stored.
- **No mass-apply:** no `apply_everywhere()`. One package at a time, daily budget enforced.
- **Idempotent execution:** repeated submissions safely detected, no duplicates.
- **Checkpoint recovery:** interrupted executions resume from last checkpoint.
- **Bounded retry:** browser resilience with configurable max retry, exponential backoff.

## Repository layout

```
backend/    FastAPI + SQLAlchemy + Alembic (Python)
  app/
    api/routes/            HTTP endpoints (health, profile, preferences, resumes,
                           jobs, applications(+execution), tracking, analytics,
                           companies, execution, queue+autopilot)
    application_execution/ Advanced automation engine (Phase 12): field catalog,
                           semantic mapper, memory, question handler, answer engine,
                           pipeline, checkpoint, resilience, human approval,
                           evidence tracker, analytics, security
    services/              domain services (discovery, quality, matching,
                           opportunity, preparation, execution, ...)
    models/                SQLAlchemy ORM models
    schemas/               Pydantic request/response contracts
    job_sources/           discovery adapters (Apify + registry/normalizer)
    ai/                    AIProvider abstraction (default mock — no external calls)
    storage/               local resume file storage
    config/                pydantic-settings (reads root .env)
    scripts/               phase backfills
    migrations/            Alembic revisions
    tests/                 pytest suite (unit + API + phase tests)
frontend/   React + Vite + Tailwind (dashboard, onboarding, jobs, companies,
            recommendations, applications + execution, resumes, profile, settings,
            skills)
docs/       Architecture, phase reports, roadmap
storage/    locally stored resume files (gitignored)
tests/      test strategy notes (unit tests live in backend/tests)
```

See `docs/ARCHITECTURE.md`, `docs/PHASE12.md`, `docs/ROADMAP.md` for details.

## Local setup

Prerequisites: Python 3.14+, Node.js 20+, and a running **PostgreSQL** server.

### 1. PostgreSQL

Create the application and test databases (adjust credentials as needed):

```powershell
psql -U postgres -c "CREATE DATABASE job_agent;"
psql -U postgres -c "CREATE DATABASE job_agent_test;"
```

### 2. Environment variables

Copy the template and fill in real values (never commit `.env`):

```powershell
Copy-Item .env.example .env
```

The backend reads the root `.env`. Key variables (see `.env.example`):

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `DATABASE_URL` | `postgresql+psycopg://postgres:CHANGE_ME@localhost:5432/job_agent` | App DB (dev). Tests use `job_agent_test`; see `backend/tests/conftest.py`. |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins. |
| `AI_PROVIDER` | `mock` | Abstract AI layer — `mock` makes zero external calls and requires no keys. |
| `APIFY_TOKEN` | *(empty)* | Required for real Apify job discovery. Optional — discovery still works with the mock source. |
| `APIFY_ACTOR_ID` | `schnellscrapers~indeed-jobs-scraper` | Apify Actor used by `POST /jobs/search`. |
| `APIFY_MAX_ITEMS`, `APIFY_RUN_TIMEOUT_SECS`, `APIFY_POLL_INTERVAL_SECS` | 20 / 300 / 5 | Apify run bounds. |
| `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB` | `storage/resumes` / 10 | Local resume storage. |

### 3. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head          # apply migrations to the job_agent DB
uvicorn app.main:app --reload # http://localhost:8000
```

### 4. Frontend

```powershell
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

### 5. Tests & lint

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest          # full suite (uses job_agent_test)
.\.venv\Scripts\python.exe -m ruff check app tests
cd ..\frontend
npm run build
```

Current gate: **532 backend tests pass**, `ruff check app tests` clean, frontend
`npm run build` passes.

Tests use a dedicated `job_agent_test` database that is created fresh per session,
recreated from schema each run, and dropped on exit. Development data in `job_agent`
is never modified.

### API docs

- OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Roadmap

See `docs/ROADMAP.md` for the full phase plan.
