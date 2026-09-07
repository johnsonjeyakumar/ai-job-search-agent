# Phase 10 — Interview Preparation & Interview Agent

## Overview

Phase 10 adds a comprehensive interview preparation workspace to the job application tracking system. Applications that reach INTERVIEW status can have detailed interview records, AI-powered question generation, answer practice, mock interview sessions, preparation plans, notes, feedback, and outcome tracking.

## Domain Model

### New Tables

| Table | Purpose |
|---|---|
| `interviews` | Interview records (schedule, type, round, interviewer, status, outcome) |
| `interview_questions` | Generated or user-created interview questions |
| `interview_sessions` | Mock interview sessions with questions, answers, feedback |
| `interview_prep_items` | Preparation plan checklist items |

### Controlled Vocabularies

- **Interview Status**: SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED, NO_SHOW, RESCHEDULED
- **Interview Outcome**: PENDING, PASSED, REJECTED, NEXT_ROUND, OFFER, WITHDRAWN, NO_DECISION
- **Interview Type**: TELEPHONE, VIDEO, TECHNICAL, BEHAVIORAL, CODING, HR, PANEL, FINAL, OTHER
- **Question Category**: TECHNICAL, BEHAVIORAL, HR, PROJECT, RESUME_BASED, ROLE_SPECIFIC
- **Question Priority**: HIGH, MEDIUM, LOW (deterministic from source + category)
- **Question Source**: JOB_REQUIREMENT, RESUME_EVIDENCE, ROLE_PATTERN, GENERAL

## Architecture Decisions

### Interview ≠ Application Lifecycle

The application `lifecycle_status` remains the authoritative state machine. Interview status is interview-specific only. Creating an interview moves the application toward INTERVIEW status (via existing `_move_toward_target`), but interview status transitions don't affect the application lifecycle.

### Reuse of Phase 8/9 Systems

- **Application lifecycle**: `record_interview` and `_move_toward_target` are reused
- **Follow-ups**: Thank-you follow-ups are scheduled via `schedule_interview_follow_up`
- **Events**: Interview creation records `INTERVIEW_SCHEDULED` event
- **AI provider**: Extended with `generate_interview_questions`, `evaluate_interview_answer`, `generate_interview_prep_summary`

### Deterministic Priorities

Question priority is determined by source + category:
- HIGH: JOB_REQUIREMENT + TECHNICAL, RESUME_EVIDENCE + PROJECT/RESUME_BASED, JOB_REQUIREMENT + ROLE_SPECIFIC
- MEDIUM: ROLE_PATTERN sources
- LOW: everything else

### AI Safety

- LLM may generate practice questions, suggest answer improvements, provide qualitative feedback
- LLM must NOT invent resume facts, job requirements, interviewer details, company facts, or interview outcomes
- Deterministic answer checks: empty, too short, too long, word count
- All generated content is labeled as AI-generated where applicable

## API Endpoints

### Interview CRUD
- `POST /interviews/applications/{id}/interviews` — Create interview
- `GET /interviews/applications/{id}/interviews` — List interviews + summary
- `GET /interviews/{id}` — Get interview details
- `PATCH /interviews/{id}` — Update interview
- `POST /interviews/{id}/status` — Change status
- `POST /interviews/{id}/complete` — Complete interview
- `POST /interviews/{id}/cancel` — Cancel interview
- `POST /interviews/{id}/reschedule` — Reschedule interview
- `POST /interviews/{id}/outcome` — Set outcome
- `POST /interviews/{id}/feedback` — Save feedback

### Questions
- `POST /interviews/applications/{id}/questions/generate` — Generate questions
- `GET /interviews/applications/{id}/questions` — List questions
- `POST /interviews/questions/{id}/answer` — Save answer
- `POST /interviews/questions/{id}/feedback` — Get feedback

### Mock Sessions
- `POST /interviews/applications/{id}/mock-sessions` — Create session
- `GET /interviews/{id}/mock-session` — Get session
- `POST /interviews/{id}/mock-session/answer` — Answer question
- `POST /interviews/{id}/mock-session/finish` — Finish session
- `GET /interviews/applications/{id}/mock-sessions` — List sessions

### Prep Plan
- `GET /interviews/applications/{id}/prep-items` — List prep items
- `PATCH /interviews/prep-items/{id}` — Update item status

## Frontend

### Pages
- `/applications/:id/interview` — Interview Workspace (5 tabs)
- Dashboard — Upcoming Interviews widget
- Application Tracking — Interview Workspace link

### Tabs
1. **Details** — Create/manage interviews, set outcomes
2. **Questions** — Generate, filter, practice answers
3. **Mock Interview** — Configure, run, evaluate
4. **Notes & Feedback** — Per-interview notes and structured feedback
5. **Prep Plan** — Checklist with progress tracking

## Testing

39 new tests covering:
- Interview CRUD + lifecycle constraints
- Question generation from job/resume context
- Deterministic priority assignment
- Answer save + deterministic feedback
- Mock session creation, answering, finish, evaluation
- Prep plan creation and status updates
- Data integrity (old records preserved, history untouched)

## Migration

Run: `python -m app.scripts.migrate_phase10`

Creates 4 new tables without modifying existing schema.
