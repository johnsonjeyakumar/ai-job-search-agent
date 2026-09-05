# Test layout

- FastAPI/unit tests live in `backend/tests/` and run with pytest.
- Root `tests/` is reserved for future end-to-end / integration suites that
  exercise both the backend and the frontend together (added in a later phase).

Run backend tests:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```