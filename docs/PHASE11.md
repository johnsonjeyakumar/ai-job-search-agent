# Phase 11: Skill Gap Analysis & Learning Plans

## Overview
Deterministic skill gap analysis that classifies job-required skills against the user's profile, generates prioritized learning plans, and tracks progress. All computation is deterministic — no LLM involvement in classification or scoring.

## Key Features

### Skill Classification (Phase 11 + 11.1)
- **MATCHED**: Skill found in profile structured data (skills, projects, internships)
- **PARTIAL**: Skill found only in resume text or interview data (weak evidence)
- **MISSING**: Skill required by job but no user evidence found
- **UNKNOWN**: Skill could not be extracted or normalized

### Evidence Hierarchy
1. `USER_VERIFIED` (7) — Explicitly verified by user
2. `RESUME` (6) — Found in resume text
3. `PROFILE` (5) — In profile structured data
4. `APPLICATION_PACKAGE` (4) — In application materials
5. `INTERVIEW` (3) — Mentioned in interview
6. `JOB_REQUIREMENT` (2) — Required by job
7. `JOB_DESCRIPTION` (1) — Mentioned in job description

### Learning Plans
- Generated per job with tasks, estimated hours, and objectives
- Items have status lifecycle: NOT_STARTED → IN_PROGRESS → COMPLETED → VERIFIED
- VERIFIED requires explicit evidence, not just completion
- PARTIAL skills are included in learning plans (need reinforcement)

### Learning Resources (Phase 11.1)
- Attach resources to learning items (courses, tutorials, videos, etc.)
- Resources can be USER added or AI_SUGGESTED
- URL validation for external links
- Resource types: COURSE, TUTORIAL, DOCUMENTATION, VIDEO, ARTICLE, BOOK, PRACTICE, PROJECT

### Skill History (Phase 11.1)
- Immutable audit trail of all status changes
- Records gap classification changes and learning progress changes
- Source tracking: GAP_ANALYSIS, LEARNING_PROGRESS
- Chronological ordering (newest first)

### Why This Skill Matters (Phase 11.1)
- Each evidence item includes a "why" explanation
- Based on market demand, role relevance, and gap impact
- Helps users understand prioritization

### Market Demand
- Computed from frequency across all collected jobs
- Demand levels: HIGH (≥40%), MEDIUM (≥20%), LOW (<20%)
- Attached to each evidence item

### Readiness Formula
- STRONG: ≥80%
- MODERATE: ≥50%
- WEAK: >0%
- UNKNOWN: 0%
- PARTIAL skills count as 50% credit

## API Endpoints

### Gap Analysis
- `POST /skills/gap-analysis/{job_id}?profile_id=X` — Run analysis
- `GET /skills/gap-analysis/{job_id}/latest` — Get latest analysis

### Learning Plans
- `GET /skills/learning-plans` — List all plans
- `POST /skills/learning-plans/{job_id}?profile_id=X` — Generate plan
- `GET /skills/learning-plans/{plan_id}` — Get plan details
- `GET /skills/learning-plans/{plan_id}/items` — Get plan items
- `PATCH /skills/learning-items/{item_id}/status` — Update item status

### Learning Resources (Phase 11.1)
- `POST /skills/learning-items/{item_id}/resources` — Add resource
- `GET /skills/learning-items/{item_id}/resources` — List resources
- `DELETE /skills/learning-resources/{resource_id}` — Delete resource

### Skill History (Phase 11.1)
- `GET /skills/history?profile_id=X&skill=Y` — Get history
- `GET /skills/history/{skill}?profile_id=X` — Get skill-specific history

### Analytics (Phase 11.1)
- `GET /skills/analytics?profile_id=X` — Get aggregate counts

## Frontend (SkillGap.jsx)

### Job Selector
- Dropdown of collected jobs
- Analyze button (requires profile)

### Gap Analysis Results
- Readiness gauge with percentage
- Market demand grid
- Skills table with: Skill, Status, Source, Evidence, Priority, Demand
- Click any skill to view detail

### Skill Detail View (Phase 11.1)
- Why this skill matters (reasons list)
- Evidence and source info
- Market demand details
- Learning resources (add/view/delete)
- Skill history timeline

### Learning Plans
- Plan cards with progress bars
- Plan detail view with items
- Status change buttons (Start, Complete, Verify)
- Resource management per item

## Tests
- `test_phase11_skill_gap.py` — Phase 11 core tests (34 tests)
- `test_phase11_1_enhancements.py` — Phase 11.1 enhancements tests (37 tests)

## Constraints
- All skill gap/readiness/priority calculations are deterministic (Python logic, never LLM)
- LLM may only assist with educational explanations, learning task wording, optional resource suggestions
- AI suggestions must be clearly marked (`AI_SUGGESTED`)
- Skill status lifecycle is separated: gap classification vs learning progress vs verification
- PARTIAL classification requires only weak evidence (RESUME, INTERVIEW)
- Learning completion does NOT imply verification
- VERIFIED requires explicit evidence
- SkillHistory is immutable
