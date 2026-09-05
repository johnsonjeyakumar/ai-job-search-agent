# Job Search & Application Agent

A personal, local-first job search and application system.

**Current status:** Phase 1 — foundation (inspection, architecture, backend + frontend scaffolds, database models, API skeleton).

## Safety rules (Phase 1 scope)

- No job scraping yet.
- No automatic application submission.
- No CAPTCHA / login / anti-bot bypass.
- Future browser automation will require explicit human approval before submission.
- Credentials are never committed (see `.env` / `.gitignore`).

## Repository layout

```
backend/    FastAPI + SQLAlchemy + Alembic (Python)
frontend/   React + Vite + Tailwind (dashboard shell)
docs/       Architecture and roadmap
tests/      Test strategy notes (unit tests live in backend/tests)
```

See `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` for details.

## Quick start

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head          # create tables in job_agent DB
uvicorn app.main:app --reload # http://localhost:8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

### API docs

- OpenAPI: http://localhost:8000/docs
- Health: http://localhost:8000/health