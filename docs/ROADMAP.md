# Roadmap

Phase plan. Each phase ends verified (tests + running servers + git check) before
the next begins. No phase auto-starts.

## Phase 1 — Foundation ✅

- [x] Inspection (existing files, environment, DB availability)
- [x] Security files: `.env`, `.env.example`, `.gitignore` (credentials untracked)
- [x] Backend scaffold: FastAPI + SQLAlchemy + Alembic + Pydantic
- [x] DB integration layer + initial migration (domain tables + `alembic_version`)
- [x] Profile / Resume / Job / Application / Recruiter / Follow-up / Automation models
- [x] API: `GET /health`, `GET/POST /profile`, `GET /resumes`, `GET /jobs`, `GET /applications`
- [x] Frontend scaffold: React + Vite + Tailwind dashboard shell (nav sections,
      placeholder stats, backend/DB health indicator)
- [x] AI / agent / job-source abstraction layers (stubs, provider-agnostic)
- [x] Tests: health, DB connection, schema-migrated, profile API & validation,
      profile & job schema validation, job model mapping — all passing
- [x] Verified: backend server, frontend server, API endpoints, DB, browser render

## Phase 2 — Profile & Preferences ✅

- [x] Profile CRUD UI + editable settings
- [x] Resume upload / versioning / active-marking
- [x] Job-search preferences as editable stored settings (locations, roles,
      experience, remote, salary) — no hard-coded values
- [x] Onboarding flow (first profile, preferred roles/locations)

## Phase 3 — Job Discovery (Apify) ✅

- [x] Apify source adapter implementing `JobSource`
- [x] Normalization + dedupe (`source` + `source_job_id` unique)
- [x] Manual run via `POST /jobs/search` with `automation_runs` logging
- [x] Jobs list UI with filters and pagination

## Phase 4 — Job Intelligence ✅

- [x] Deterministic job-quality scoring (freshness, description, requirements,
      application, company, location, salary) with component explanations
- [x] `GET /jobs/{id}/match` and scoring plumbing; stats on the jobs list
- [x] Quality gates feed later phases; backfill script `app/scripts/phase4_backfill.py`

## Phase 5 — Personal Matching & Opportunity Scoring ✅

- [x] `AIProvider` concrete layer with a strict output contract (the LLM may never
      emit scores — anything out of contract is rejected wholesale)
- [x] Transparent match scoring → `job_matches` (score, breakdown, matched/missing
      skills, blockers)
- [x] Opportunity score blending match + quality + freshness + company signals
- [x] APPLY / REVIEW / SKIP-style recommendations with explainability
- [x] Recommendations UI + Match/Opportunity panels on the job page
- [x] Backfill script `app/scripts/phase5_backfill.py`; see `docs/PHASE5.md`

## Phase 6 — Application Preparation ✅

- [x] Application package per job: quality gate, deterministic answers, cover
      letter drafts, per-job resume selection, answer editing
- [x] Package lifecycle: prepare → validate → approve → archive/regenerate
- [x] Applications UI + `/applications` and `/applications/{id}/preview` endpoints
- [x] Migration `e60a8f4d2c71_phase6_application_preparation.py`

## Phase 7 — Platform-Aware Application Execution ✅

- [x] Execution engine: detect platform → resolve policy → run safe steps only →
      stop at the human approval boundary
- [x] Per-platform policy defaults (boards = `HUMAN_ASSISTED`; career sites /
      generic = `PERMITTED_BROWSER`), user-overridable via Preferences
- [x] Mock + Playwright browser drivers, deterministic field mapping (never guesses
      sensitive/unknown fields), no CAPTCHA/login/anti-bot bypass
- [x] Ordered step trail, evidence, confirmation reference/URL, daily budget,
      duplicate protection
- [x] Execution UI at `/applications/:id/execute`
- [x] Migration `f7a3b9c2d1e5_phase7_application_execution.py`; see `docs/PHASE7.md`

## Phase 8 — n8n Workflow Automation (PLANNED)

- Orchestrate repeated discovery / preparation / follow-up flows in n8n, still
  calling the same approved, human-gated engine. **Not implemented yet.** No Phase 7
  behavior changes.

## Phase 9 — Follow-Up Automation Engine + Resume & Job-Source Analytics ✅

- [x] Follow-up engine on top of application tracking: reasons
      (`SUBMISSION_FOLLOW_UP`, `INTERVIEW_THANK_YOU`), priorities
      (`HIGH`/`MEDIUM`/`LOW`), `trigger_key` dedupe, derived lifecycle states
      (`SCHEDULED`/`DUE`/`OVERDUE`/`RESCHEDULED`/`SKIPPED`/…); skip / restore /
      cancel / complete / reschedule actions with immutable timeline events
- [x] Interview thank-you scheduling wired into `record_interview`
      (`interview_follow_up_days` preference)
- [x] `application_source` captured from the real recorded execution platform
      (never fabricated)
- [x] Analytics: source quality (discovery + submission, explicit deterministic
      score + bands), resume performance + recommended resume, response-time
      breakdowns, deterministic evidence-only insights
- [x] Follow-up filtered list + health endpoints on `/tracking` + `/analytics`
- [x] Dashboard follow-up card (OVERDUE / DUE / UPCOMING + actions), tracking
      detail follow-up UX, new `/analytics` page
- [x] Migration `b3e7d2f1a9c4`; 23 new tests; full suite 344✅; see
      `docs/PHASE9.md`
- [ ] Recruiter contact automation deliberately out of scope (no email/messaging
      automation) — recruiters remain a manual, tracked list

## Phase 10 — Multi-Provider & Production Hardening ✅

- Concrete AI provider + expandable Apify/generic job sources
- Auth, deployment, real-driver coverage for platforms where automation is
  explicitly permitted

## Phase 11 — Skill Taxonomy, Evidence & Market Intelligence ✅

- [x] Skill taxonomy with 130+ canonical names
- [x] Strong/weak evidence separation
- [x] "Why this skill matters" builder
- [x] Skill history with immutable records
- [x] Learning resources with URL validation
- [x] Enhanced readiness formula (PARTIAL=50% credit)
- [x] Market demand intelligence
- [x] Interview signal detection
- [x] Confidence scoring
- [x] Learning plans with PARTIAL skills
- [x] Practical tasks with evidence verification
- [x] 37 new tests; full suite 477✅

## Phase 11.1 — Frontend Enhancements ✅

- [x] Skill detail view with evidence, resources, history
- [x] Enhanced learning workspace with resource management
- [x] Demand column in skills table
- [x] Playwright E2E verification
- [x] Phase 11 documentation

## Phase 12 — Advanced Application Automation Engine ✅

- [x] Semantic field mapping with multi-strategy approach
- [x] Application memory with verified answer reuse
- [x] Question normalization and classification
- [x] Evidence-bound answer generation
- [x] 8-stage mapping pipeline
- [x] Checkpointing and execution recovery
- [x] Browser resilience and retry logic
- [x] Human approval boundaries
- [x] Idempotency for safe retries
- [x] Execution evidence tracking
- [x] Analytics and performance metrics
- [x] Security controls and field classification
- [x] API endpoints for all components
- [x] 49 new tests; full suite 526✅
- [x] Documentation: `docs/PHASE12.md`

## Phase 13 — Browser Automation Integration (PLANNED)

- Real Playwright browser drivers for each platform
- Automated form filling with human approval
- CAPTCHA detection and human handoff
- Session management and cookie handling

## Safety constraints (all phases)

- No mass-apply / auto-submit without human approval — approval gates remain in
  every phase; `apply_everywhere()` is deliberately excluded.
- No bypassing CAPTCHA, logins, anti-bot systems, or rate limits.
- Credentials, cookies, and browser sessions never committed to the repo.