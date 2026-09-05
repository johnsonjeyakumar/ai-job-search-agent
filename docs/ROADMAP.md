# Roadmap

Phase plan. Each phase ends verified (tests + running servers + git check) before
the next begins. No phase auto-starts.

## Phase 1 — Foundation ✅ (current)

- [x] Inspection (existing files, environment, DB availability)
- [x] Security files: `.env`, `.env.example`, `.gitignore` (credentials untracked)
- [x] Backend scaffold: FastAPI + SQLAlchemy + Alembic + Pydantic
- [x] DB integration layer + initial migration (9 domain tables + `alembic_version`)
- [x] Profile / Resume / Job / Application / Recruiter / Follow-up / Automation models
- [x] API: `GET /health`, `GET/POST /profile`, `GET /resumes`, `GET /jobs`, `GET /applications`
- [x] Frontend scaffold: React + Vite + Tailwind dashboard shell (9 nav sections,
      placeholder stats, backend/DB health indicator)
- [x] AI / agent / job-source abstraction layers (stubs, provider-agnostic)
- [x] Tests: health, DB connection, schema-migrated, profile API & validation,
      profile & job schema validation, job model mapping — all passing
- [x] Verified: backend server, frontend server, API endpoints, DB, browser render

## Phase 2 — Profile & Preferences

- Profile CRUD UI + editable settings
- Resume upload / versioning / active-marking
- Job-search preferences as editable stored settings (locations, roles, experience,
  remote, salary) — no hard-coded values
- Onboarding flow (first profile, preferred roles/locations)

## Phase 3 — Job Discovery

- Apify source adapter(s) implementing `JobSource`
- Normalization + dedupe (`source` + `source_job_id` unique)
- Manual run + scheduled discovery with `automation_runs` logging
- Jobs list UI with filters and pagination

## Phase 4 — Matching & Recommendations

- `AIProvider` concrete implementation (provider selected via `AI_PROVIDER`)
- Transparent match scoring → `job_matches` (score, breakdown, matched/missing skills)
- APPLY / REVIEW / SKIP recommendations with explainability
- Recommendations UI

## Phase 5 — Applications & Preparation

- Application tracking CRUD + whole lifecycle UI (applied, interviewing, offer, etc.)
- Tailored resume selection per job
- AI answer generation + cover letter drafts (always reviewable)

## Phase 6 — Browser Automation (guiarded)

- Playwright-based submission flow ONLY where platforms permit automation
- Explicit human approval gate before any final submission
- Rate-limit responsibility, no CAPTCHA/login/anti-bot bypass
- Session persistence handled securely (`browser sessions` never committed)

## Phase 7 — Recruiters, Follow-ups & Logs

- Recruiter contacts and follow-up scheduling
- Automation run/error log UI consumed from `automation_runs` / `automation_errors`
- Reporting & analytics on the dashboard

## Safety constraints (all phases)

- No mass-apply / auto-submit without human approval.
- No bypassing CAPTCHA, logins, anti-bot systems, or rate limits.
- Credentials, cookies, and browser sessions never committed to the repo.