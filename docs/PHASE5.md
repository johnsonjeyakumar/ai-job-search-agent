# Phase 5 — AI Personal Job Matching & Opportunity Decision Engine

Status: **complete and verified** (backend, frontend UI, build, browser checks).

This phase replaced opaque scoring with a transparent, **deterministic-first** engine:
weights are config, every score carries an explanation, missing signals are treated
as **UNKNOWN and excluded** (never guessed, never penalized), and AI is only used for
one narrow, non-fabricating task.

## What was built

- **Skill normalization** — `app/services/skill_normalizer.py`: canonical names,
  aliases, normalized matching for skills/reasons (e.g. `React.Js!` → `react.js`).
- **Structured requirement extraction** — `app/services/requirement_extractor.py`:
  pulls skills, certifications, education, and bounded experience from job titles +
  descriptions. AI (`AIProvider.extract_job_requirements`) may refine the job
  description analysis, but the mock provider returns `None` (no fabrication), and
  everything falls back to the deterministic extractor.
- **Personal match** — `app/services/matching_service.py`: per-component scoring
  (skills, experience, role, location, education, remote, employment_type, salary,
  certifications), component messages, evidence list, and blockers.
- **Opportunity score** — `app/services/opportunity_service.py`: blends personal match
  with Phase 4 listing-quality, freshness, and company signals into one decision score.
- **Storage & plumbing** — `JobMatch` + `OpportunityScore` models (migration
  `c7e5b2f9a3d4_phase5_matching.py`), `MatchesStatsRead` stats block, `job_intel`
  enrich hook on job reads, new filters/sorts, and `GET /jobs/{id}/match` /
  `GET /jobs/{id}/opportunity` endpoints.
- **Backfill** — `app/scripts/phase5_backfill.py` (re-run on the finalized code).
- **Frontend** — Jobs list (recommendation + min-score filters, match/opportunity
  sort and chips), Job detail (Match + Opportunity panels with component breakdown,
  requirement buckets, blockers), Dashboard "Match Intelligence" block, and a
  grouped Recommendations page. `npm run build` passes; all pages verified in a real
  browser (Chrome, Playwright) with no new console errors.

## Weights (config, `settings.py`)

**Match** — components only measured when the job specifies them; weights are
normalized over the available (UNKNOWN-excluded) components:

| Component         | Weight |
| ----------------- | ------ |
| skills            | 0.35   |
| experience        | 0.20   |
| role              | 0.15   |
| location          | 0.10   |
| education         | 0.08   |
| remote            | 0.05   |
| employment_type   | 0.03   |
| salary            | 0.02   |
| certifications    | 0.02   |

**Opportunity** = 0.70 · match + 0.20 · quality + 0.05 · freshness + 0.05 · company
(normalized over available components).

## Bands & caps

`band_for_score` (applies to both match and opportunity):

| Score   | Recommendation |
| ------- | -------------- |
| ≥ 90    | APPLY_NOW      |
| ≥ 80    | APPLY          |
| ≥ 65    | REVIEW         |
| ≥ 50    | LOW_PRIORITY   |
| < 50    | SKIP           |
| None    | REVIEW         |

Opportunity caps (applied as `score = min(score, cap)`, surfaced in the explanation):

- posting **STALE** → capped at **55**
- listing quality **< 30** → capped at **45**
- match **not evaluable** → capped at **60**

**Blockers** always win: an experience requirement beyond the candidate's indicated
level, or a clearly unrelated role family, forces **SKIP** regardless of the numbers.

## Current live distribution (dev data, 33 jobs)

```
APPLY_NOW      0
APPLY         14
REVIEW        19
LOW_PRIORITY   0
SKIP           0
avg match     93/100      avg opportunity  80/100      avg quality 47/100
```

## Honesty limitations (important)

- **No profile is stored** in the dev DB (`GET /profile` → 404), so the engine runs
  against default preferences (Chennai/Madurai/Remote-India, Fresher/0–2 years,
  8 target roles, all remote/employment types, min match 60). Scores reflect those
  defaults, not a real user.
- The collected real jobs have **no descriptions**, **no `posted_date`**, and no
  skills/education/certifications stored. As a result:
  - **freshness = UNKNOWN** for every job (freshness component excluded).
  - skills / education / certifications components are **UNKNOWN** (excluded).
  - match scores cluster high (87–100) largely because scoring runs on sparse data
    with a small set of measured components — this is data sparseness, not evidence
    the jobs are strong fits.
- The 7 salary-bearing jobs still parse through the final `parse_salary` (unit-aware):
  LPA/lakh ≤ 200, "per annum" ≤ 2,000,000, "k" ≤ 1000k, else ≤ 200.
- Nothing was auto-applied or submitted; this phase ranks and recommends only.

## AI output contract (enforced)

The LLM is **never allowed to emit scores**. It may only return structured facts
(`required_skills`, `preferred_skills`, `experience_requirement`, `role`,
`location`, `education_requirement`, `certifications`) plus `evidence` and
`confidence` — nothing else.

- Contract: `app/schemas/ai.py` (`AIJobInterpretation`, `extra="forbid"`).
- Every provider payload is Pydantic-validated in
  `requirement_extractor.refine_with_ai` **before it can influence scoring**.
  A provider that returns `match_score`, `opportunity_score`,
  `recommendation`, or any out-of-contract key is rejected wholesale and the
  engine falls back to the deterministic extractor.
- `confidence` is recorded as metadata and never multipled into weights, so
  the same structured input always yields the same score. Weights, bands,
  caps, and blockers live only in deterministic Python
  (`matching_service.calculate`, `opportunity_service.calculate`).
- Component scores, personal match score, opportunity score, and the
  recommendation are computed exclusively by the engine
  (`matching_service.py:281`); a provider cannot inject a score even if it
  tries (`calculate` accepts only a pre-validated requirement bundle).
- Covered by `TestAIOutputContract` + `TestDeterministicScoring` (score-key
  rejection, fallback on None/non-dict/invalid confidence, merge determinism,
  same-input-same-score, and "a sneaky score payload cannot move the outcome").

## Gates

- Full backend suite: **200 passed**, ruff **clean**.
- Frontend `npm run build` **passes**; Chrome/Playwright checks on `/`, `/jobs`,
  `/jobs/{id}`, `/recommendations` pass with no new console errors.
- Both servers running (backend :8000 restarted on final code, frontend :5173).

**Next: user approval gates before Phase 6 (browser automation) work begins.**