# Job Search & Application Agent

A personal, **local-first** job search and application system: discovers jobs via
Apify, scores them with a transparent deterministic-first engine, prepares a
tailored application package, and runs a **safe, human-gated application execution**
workflow against the platform where the job lives.

**Current status:** Phases 1–7 implemented and verified. Phase 8+ planned (see
Roadmap). No automatic mass-application, and nothing is ever submitted without an
explicit, per-package human approval.

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

## Current capabilities

- Discover remote/on-site software jobs through an Apify Indeed scraper
  (source-agnostic, deduplicated, logged as automation runs).
- Score every job with transparent, explainable quality + personal-match +
  opportunity signals; OPTIONAL/blocked jobs are surfaced with reasons.
- Prepare a reviewable application package per job (deterministic answers from your
  profile, tailored cover letter, per-job resume selection, quality gate).
- Execute approved packages through a platform-aware runner that:
  - detects the platform and resolves its automation policy,
  - fills known fields only — never guesses phone/experience/notice-period or any
    unknown/sensitive field,
  - stops at `AWAITING_APPROVAL` for a human decision,
  - either auto-submits after approval (only where the platform policy permits) or
    stops at `AWAITING_USER` for a manually-completed, honestly-confirmed outcome,
  - records an ordered step trail, warnings, evidence, confirmation reference/URL,
    and enforces a configurable daily application budget.
- Full dashboard: jobs, companies, recommendations, applications (+ execution),
  resumes, recruiters, profile, preferences, settings, logs.

## Safety / execution model

- **Human approval gate:** an application package must be APPROVED (Phase 6) and
  each execution must be explicitly approved before any submission is attempted.
- **Authorized automation where applicable:** platforms whose resolved policy is
  `PERMITTED_BROWSER` (e.g. company career sites) may fill known fields
  automatically and submit only after approval. LinkedIn / Indeed / Naukri default to
  `HUMAN_ASSISTED` — the engine fills safe fields and stops; the human completes and
  confirms. Platform modes are configurable live via Preferences.
- **Human-assisted workflows where required:** any platform (or user override) in
  `HUMAN_ASSISTED` mode never auto-submits; the outcome is recorded as
  `CONFIRMED` / `LIKELY` / `UNKNOWN` / `FAILED` by the user, and only explicit
  evidence marks a submission `SUBMISSION_CONFIRMED`.
- **No CAPTCHA / anti-bot bypass:** CAPTCHA, login-required, and anti-bot preflight
  checks stop the run with a **blocked** step — nothing is submitted around them.
- **No credential bypass:** no passwords or cookies are collected, stored, or used
  to log in on your behalf.
- **No mass-apply:** there is deliberately no `apply_everywhere()`. The runner only
  ever executes the one package you approve, and the daily budget guards repeated
  submissions.
- Credentials, tokens, cookies, and persisted browser sessions are never committed
  (see `.env` / `.gitignore`).

## Repository layout

```
backend/    FastAPI + SQLAlchemy + Alembic (Python)
  app/
    api/routes/            HTTP endpoints (health, profile, preferences, resumes,
                           jobs, applications(+execution), companies)
    application_execution/ Phase 7 execution engine: detector, policy, fields,
                           browser drivers (mock + Playwright), executor, adapters
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
            recommendations, applications + execution, resumes, profile, settings)
docs/       Architecture, phase reports, roadmap
storage/    locally stored resume files (gitignored)
tests/      test strategy notes (unit tests live in backend/tests)
```

See `docs/ARCHITECTURE.md`, `docs/PHASE5.md`, `docs/PHASE7.md`, and
`docs/ROADMAP.md` for details.

## Local setup

Prerequsites: Python 3.11+, Node.js 20+, and a running **PostgreSQL** server.

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
.\.venv\Scripts\python.exe -m pytest          # full suite
.\.venv\Scripts\python.exe -m ruff check app tests
cd ..\frontend
npm run build
```

Current gate: **277 backend tests pass**, `ruff check app tests` clean, frontend
`npm run build` passes.

### API docs

- OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Roadmap

- **Phase 8 — n8n workflow automation (PLANNED, not implemented).** Orchestrate
  repeated discovery / preparation / follow-up flows in n8n, still calling the
  same approved, human-gated engine. No phase-7 behavior changes.
- **Phase 9 — Recruiters, follow-ups & analytics.** Recruiter contacts, follow-up
  scheduling, and the automation-run / error log UI together with dashboards.
- **Phase 10 — Multi-provider & production hardening.** Concrete AI provider,
  additional Apify/generic job sources, auth, deployment, and real-driver coverage
  for platforms where automation is explicitly permitted.

See `docs/ROADMAP.md` for the full phase plan.