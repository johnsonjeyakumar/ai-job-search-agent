# Architecture

Personal, local-first job search & application agent.

## Principles

1. **Human-in-the-loop** — the system may prepare and even automate steps, but it
   never final-submits an application without explicit human approval.
2. **Source-agnostic discovery** — every job source (Apify actors, REST APIs,
   custom scrapers in later phases) normalizes output to the shared `Job` model.
3. **Provider-agnostic AI** — all AI calls go through `app/ai/base.py`
   (`AIProvider`); which provider is active is decided by `AI_PROVIDER`
   (default `mock` — no external calls, zero keys required).
4. **Everything trackable** — automation runs and errors are recorded
   (`automation_runs`, `automation_errors`) so nothing the agent does is silent.
5. **No fabricated data / no destructive operations** — Phase 1 creates tables via
   migrations only; it never inserts production-looking fake data and never
   drops/resets existing databases.

## Layers

| Layer           | Location                          | Responsibility                              |
| --------------- | --------------------------------- | ------------------------------------------- |
| API             | `backend/app/api/routes/`         | HTTP endpoints, validation, error handling  |
| Schemas         | `backend/app/schemas/`            | Pydantic request/response contracts         |
| Services        | `backend/app/services/`           | Thin domain operations over models          |
| Models          | `backend/app/models/`             | SQLAlchemy ORM models                       |
| Agents          | `backend/app/agents/`             | Future orchestration agents (stubs)         |
| Job sources     | `backend/app/job_sources/`        | Discovery adapters (registry, no impl yet)  |
| AI              | `backend/app/ai/`                 | Abstract provider + mock implementation     |
| Database        | `backend/app/database/`           | Engine/session, declarative base            |
| Config          | `backend/app/config/`             | `pydantic-settings`, reads `.env`           |
| Migrations      | `backend/migrations/`             | Alembic revisions                           |
| Frontend        | `frontend/src/`                   | React + Vite + Tailwind dashboard shell     |

## Data flow (future)

```
JobSource ──► normalize ──► jobs (DB)
                               │
                   AIProvider.analyze_job(job, profile)
                               │
                        job_matches (score + breakdown)
                               │
            recommend APPLY / REVIEW / SKIP  (human approves)
                               │
                resume + AI answers + cover letter ──► draft
                               │
        Playwright (only where permitted) ──► submit ──► applications
```

## API surface (Phase 1)

| Method | Path             | Purpose                                |
| ------ | ---------------- | -------------------------------------- |
| GET    | `/health`        | Service + database liveness            |
| GET    | `/profile`       | Current profile (404 if none)          |
| POST   | `/profile`       | Create or update the profile           |
| GET    | `/resumes`       | List resumes                           |
| GET    | `/jobs`          | List jobs                              |
| GET    | `/applications`  | List applications                      |

OpenAPI docs served at `/docs`.

## Configuration

All runtime configuration lives in the environment (root `.env`, gitignored).
`.env.example` documents every variable. Credentials and tokens must never be
committed (confirmed by root `.gitignore`).

## Naming / conventions

- Python: type annotations everywhere, `ruff` (E, F, I, W) enforced, 100 cols.
- SQLAlchemy 2.0 style (`Mapped[...]`, `mapped_column`).
- PostgreSQL JSONB columns for list/dict attributes (skills, preferences, etc.).
- Pydantic v2 schemas with `from_attributes=True` for read models.