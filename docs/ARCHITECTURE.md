# Architecture

Personal, local-first job search & application agent.

## Principles

1. **Human-in-the-loop** — the system prepares and may automate safe steps, but it
   never final-submits an application without explicit human approval (Phase 6
   package approval + Phase 7 execution approval).
2. **Source-agnostic discovery** — every job source (Apify actor today, more
   adapters later) normalizes output to the shared `Job` model.
3. **Provider-agnostic AI** — all AI calls go through `app/ai/base.py`
   (`AIProvider`); which provider is active is decided by `AI_PROVIDER`
   (default `mock` — no external calls, zero keys required).
4. **Everything trackable** — automation runs and errors are recorded
   (`automation_runs`, `automation_errors`), and Phase 7 executions record an
   ordered step trail + evidence, so nothing the agent does is silent.
5. **Deterministic-first, no fabricated data** — scoring and answer generation are
   deterministic; AI output is contract-validated and never fabricates. Migration
   history is additive; nothing drops or resets existing data.
6. **Evidence-backed tracking & analytics** — application lifecycle, follow-up
   state, and every rate/quality/rank metric are derived from immutable history
   (or honest `Limited data`/`Insufficient data` labels), never from guesses; the
   follow-up engine and analytics are plain deterministic Python, with no LLM.

## Layers

| Layer           | Location                          | Responsibility                              |
| --------------- | --------------------------------- | ------------------------------------------- |
| API             | `backend/app/api/routes/`         | HTTP endpoints, validation, error handling  |
| Schemas         | `backend/app/schemas/`            | Pydantic request/response contracts         |
| Services        | `backend/app/services/`           | Domain operations over models (quality, match, preparation, execution, ...) |
| Models          | `backend/app/models/`             | SQLAlchemy ORM models                       |
| Agents          | `backend/app/agents/`             | Orchestration agents (stubs)                |
| Job sources     | `backend/app/job_sources/`        | Discovery adapters (Apify impl. + registry + normalizer) |
| AI              | `backend/app/ai/`                 | Abstract provider + mock implementation     |
| Execution       | `backend/app/application_execution/` | Phase 7 runner: detector, policy, fields, browser drivers (mock + Playwright), executor, platform adapters |
| Database        | `backend/app/database/`           | Engine/session, declarative base            |
| Config          | `backend/app/config/`             | `pydantic-settings`, reads `.env`           |
| Migrations      | `backend/migrations/`             | Alembic revisions                           |
| Frontend        | `frontend/src/`                   | React + Vite + Tailwind dashboard           |

## Data flow

```
JobSource (Apify) ──► normalize ──► jobs (DB)
                                        │
                       quality score  job_matches  opportunity score
                                        │
                   APPLY / REVIEW / SKIP (transparent, deterministic)
                                        │
            application package (approve gate) ──► draft (answers + cover letter)
                                        │
   platform detector ─► policy (HUMAN_ASSISTED / PERMITTED_BROWSER)
                                        │
        execution: known fields only, no anti-bot bypass, step trail
                                        │
         approval ─► submission ─► applications (+evidence, confirmation)
                                         │
        application lifecycle + follow-up engine (typed reasons, priorities,
        trigger-keys, derived due states) ─► immutable timeline events
                                         │
    analytics: funnel, response times, source quality, resume rank →
    recommended resume, insights, follow-up health (deterministic)
```

## API surface

Endpoints live under `backend/app/api/routes/` (see the running server's
`/docs` for the full OpenAPI spec). Highlights:

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET    | `/health` | Service + database liveness |
| GET/POST/PUT | `/profile` | Read / create / update the profile |
| GET/PUT | `/preferences` | Read / update job-search preferences (incl. platform policies) |
| GET/POST/PUT/DELETE | `/resumes` | Resumes + file upload/versioning |
| GET    | `/jobs`, `/jobs/stats`, `/jobs/{id}` | List / stats / detail |
| POST   | `/jobs/search` | Trigger Apify-backed discovery (202, automation-run logged) |
| GET    | `/jobs/{id}/match`, `/jobs/{id}/opportunity` | Scores + explainability |
| GET/POST/PUT | `/applications` | Package list / prepare / detail |
| POST/PUT | `/applications/{id}/approve`, `/validate`, `/regenerate`, `/archive`, `/answers/{answer_id}`, `/cover-letter` | Package lifecycle |
| GET/POST | `/applications/{id}/execution(/budget)` | Execution UI + budget |
| POST    | `/applications/{id}/execution/{execution_id}/approve\|cancel\|resume\|confirm` | Execution control |
| GET     | `/tracking/applications`, `/tracking/applications/{id}` | Application lifecycle + timeline view |
| POST/PATCH | `/tracking/applications/{id}/status\|notes\|responses\|interviews\|offers\|follow-ups` | Lifecycle / event recording |
| GET/POST | `/tracking/follow-ups`, `/tracking/follow-ups/summary`, `/tracking/follow-ups/{id}`, `.../{id}/complete\|skip\|restore\|reschedule\|cancel` | Follow-up engine API |
| GET     | `/analytics/*` (funnel, roles, locations, companies, sources, resumes, resumes/compare, recommended-resume, sources/performance, response-times, response-times/breakdowns, insights, follow-ups, trends, applications) | Deterministic analytics |
| GET     | `/companies` | Companies |

## Configuration

All runtime configuration lives in the environment (root `.env`, gitignored).
`.env.example` documents every variable. Credentials and tokens must never be
committed (confirmed by root `.gitignore`).

## Naming / conventions

- Python: type annotations everywhere, `ruff` (E, F, I, W) enforced, 100 cols.
- SQLAlchemy 2.0 style (`Mapped[...]`, `mapped_column`).
- PostgreSQL JSONB columns for list/dict attributes (skills, preferences, etc.).
- Pydantic v2 schemas with `from_attributes=True` for read models.