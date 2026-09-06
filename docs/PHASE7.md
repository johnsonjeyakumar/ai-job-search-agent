# Phase 7 — Safe Application Execution Engine

Status: **complete and verified** (backend, frontend UI, build, browser checks,
mock-driver end-to-end).

Phase 7 turns an **APPROVED** Phase-6 application package into a **safe, recorded
execution**: detect the platform, resolve the per-platform policy, run only the
known-safe steps, and stop at the human approval boundary. Two policy-shaped
outcomes exist — the engine either submits automatically after approval (where the
platform policy allows it) or stops at `AWAITING_USER` and lets the human confirm
honestly. It never bypasses CAPTCHA, login, anti-bot, or rate limits; it never
guesses a sensitive or unknown field; and there is deliberately **no
`apply_everywhere()`**.

## What was built

- **Execution schema** — models + migration
  `f7a3b9c2d1e5_phase7_application_execution.py`: `application_executions`
  (platform, mode, status, approval_payload, warnings, execution_summary,
  daily_budget, submission_status, confirmation_url/reference, timestamps),
  `application_execution_steps` (ordered step trail, append/update in place),
  `application_execution_evidence` (verification markers), plus
  user-configurable `daily_application_target` / `daily_application_maximum` /
  `platform_policies` on `preferences`. Nothing Phase 4/5/6 drops or re-writes.
- **Platform detection** — `app/application_execution/detector.py`: honors the
  crawl `source` label (linkedin/indeed/naukri), known board hosts, well-known ATS
  hosts (greenhouse, lever, workday, icims, workable, ...) → `company_career`, a
  careers-looking subdomain or ATS path marker (`/apply/`, `/jobs/`, `/careers/`, ...)
  → `company_career`, otherwise `generic`.
- **Policy resolution** — `app/application_execution/policy.py`: safe defaults
  (linkedin/indeed/naukri → `HUMAN_ASSISTED`; `company_career`/`generic` →
  `PERMITTED_BROWSER`), overridable per user via `platform_policies`; invalid or
  unknown stored modes degrade to `HUMAN_ASSISTED`.
- **Browser drivers** — `app/application_execution/browser.py`: `MockBrowserDriver`
  (deterministic, `mock://` only, 10 scripted scenarios incl. captcha, login-required,
  validation-error, failed-submit, confirmation, unknown-field, resume-upload,
  dropdowns, new-question) and `PlaywrightBrowserDriver` (lazy-imported, real page
  automation for the approved browser mode). Scenario is selected from the mock
  hostname or the last path segment, so platform lookalike hosts combine with any
  scenario (`mock://careers.acme.com/apply/validation-error` = company_career +
  validation-error).
- **Field mapping** — `app/application_execution/fields.py`: known fields are
  filled from prepared answers/profile via `FIELD_SPECS` (deterministic, no AI);
  never-guess fields (phone, experience, notice period, ...) and unknown required
  fields stop the run; new open-ended questions become `review_question`.
- **Executor** — `app/application_execution/executor.py`: start (duplicate
  protection + daily budget), resume-only-on-stalled, `_payload_dict` (fills,
  fields_detected, required_unfilled labels, new_questions, recommended_action,
  auto_submit_allowed, resume_uploaded, warnings), `_record_step` (an in-flight
  `running` row is completed in place — the trail has one row per step).
- **Platform adapters** — `app/application_execution/adapters/`: registry + base
  contract (fill / submit / resume-upload / login gating per mode); concrete
  `linkedin`, `indeed`, `naukri`, `company_career`, `generic`, `human_assisted`.
  All refuse anything outside their lane:
  - `HumanAssistedAdapter` — never allows automated submit, even in
    `PERMITTED_BROWSER`; resume upload only where lawful.
  - `generic` — fills known fields in a permitted session but **never** auto-submits
    (approve → `AWAITING_USER`, human finishes and confirms).
  - `company_career` — overrides nothing from base, so in `PERMITTED_BROWSER` it may
    auto-submit after approval.
- **Service & routes** — `application_execution_service.py` + execution endpoints on
  `app/api/routes/applications.py`: `GET .../execution` (preview + serialized
  execution), `POST .../execute`, `POST .../execution/{id}/approve|cancel|resume|confirm`,
  `GET .../execution/budget`.
- **Frontend** — `pages/ExecutionPage.jsx` at `/applications/:id/execute`: execution
  preview (platform, resolved mode, budget, warnings), status badge, safe-execution
  summary (filled fields, required-unfilled, new questions, recommended action),
  ordered step trail, evidence list, and the approve / cancel / resume / confirm
  actions. `pages/Applications.jsx` lists packages and links into the execute page.
- **Mock browser test pages** — `backend/tests/mock_pages/` (10 HTML scenarios:
  simple-form, dropdowns, unknown-field, resume-upload, validation-error, captcha,
  login-required, new-question, confirmation, failed-submit).

## Behavior contract

- **SUBMITTED** only when a submission actually occurred; **SUBMISSION_CONFIRMED**
  only when there is explicit evidence (auto-captured confirmation markers, or a
  human `CONFIRMED` outcome with reference/url). `LIKELY`/`UNKNOWN` keep data honest
  without claiming confirmation — the run is marked SUBMITTED but not CONFIRMED.
- Approval gates everything: a package must be `APPROVED`; re-validation is skipped
  for already-approved packages (answer edits never re-mark INVALID); approve on a
  `REVOKED` package → 409 and `BLOCKED`.
- Duplicate protection: a second run for an already-submitted job is rejected; a
  package has one execution; terminal executions reject approve/cancel with 409.
- Daily budget: `used_today` counts confirmed/local submissions in `AutomationRun`;
  hitting `daily_application_maximum` blocks further submissions.
- CAPTCHA (`blocker=="captcha"`), anti-bot, and login-required preflight checks stop
  the run with a **blocked** step; nothing is ever submitted around them.
- Secrets: no passwords/credentials are collected or stored; `confirmation_url` and
  references are evidence, not credentials.

## Platform | Mode | Tested

| Platform | Default mode | Auto-submit allowed | Verified |
| --- | --- | --- | --- |
| linkedin | HUMAN_ASSISTED | No — human completes & confirms | unit (policy + adapter) |
| indeed | HUMAN_ASSISTED | No — human completes & confirms | unit (policy + adapter) |
| naukri | HUMAN_ASSISTED | No — human completes & confirms | unit (policy + adapter) |
| company_career | PERMITTED_BROWSER | Yes (after approval) | unit + browser E2E `mock://careers.acme.com/apply/simple-form` → approve → SUBMISSION_CONFIRMED + REF-SIMPLE-FORM evidence |
| generic | PERMITTED_BROWSER | No — approve → AWAITING_USER | unit + browser E2E `mock://opendesk.example/q/simple-form` → approve → AWAITING_USER → confirm → SUBMISSION_CONFIRMED + REF-GENERIC-777 |

This table records what Phase 7 drives and gates. It is **not** an authorization
grant: automated submission is enabled only when the stored platform policy for a
session says `PERMITTED_BROWSER`, and defaults for the major boards are
`HUMAN_ASSISTED`.

## Gates

- Full backend suite green — includes 41 Phase 7 tests (mapping, adapters, policy,
  steps ordering, duplicates, daily budget, captcha block, validation-fail
  block, resume-upload, new-question/unknown-field stops, generic manual flow,
  company-career auto-submit flow, cancel-after-terminal 409).
- `ruff check app tests` **clean**.
- Frontend `npm run build` **passes**; real-browser (Playwright) verification of the
  execute page: run → approve → auto-submit with captured evidence, and run →
  approve → manual confirm (generic) with recorded reference/URL. No new console
  errors.
- Migration applied to the dev DB; backend (:8000) restarted on final code, frontend
  dev server (:5173) running.

**Next: STOP.** Phase 8 (mass application) is deliberately out of scope.