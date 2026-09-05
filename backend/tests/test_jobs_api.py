"""Jobs API: listing/filtering/pagination, search execution, run logging, dedup."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.database.session import get_db
from app.job_sources import ScrapeResult
from app.main import app as fastapi_app

_JOB_KEYS = {"source_job_id": set()}


def _next_key(prefix):
    key = None
    n = 0
    while key is None or key in _JOB_KEYS["source_job_id"]:
        n += 1
        key = f"{prefix}{n}"
    _JOB_KEYS["source_job_id"].add(key)
    return key


@pytest.fixture
def client_db(db_engine):
    """TestClient overriding get_db AND background-task SessionLocal to the test engine."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    def override_get_db():
        try:
            yield session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = override_get_db

    import app.api.routes.jobs as jobs_routes

    original = jobs_routes.SessionLocal
    jobs_routes.SessionLocal = sessionmaker(bind=db_engine)
    try:
        with TestClient(fastapi_app) as client:
            yield client, session
    finally:
        jobs_routes.SessionLocal = original
        fastapi_app.dependency_overrides.pop(get_db, None)
        session.close()
        transaction.rollback()
        connection.close()


def _scrape_result(jobs, invalid=None, raw_count=None):
    return ScrapeResult(
        source="apify",
        raw_count=raw_count if raw_count is not None else len(jobs) + len(invalid or []),
        jobs=jobs,
        invalid=invalid or [],
    )


def _build_job(title, company, **extra):
    return {
        "title": title,
        "company": company,
        "source": "apify",
        "source_job_id": extra.pop("source_job_id", None),
        "url": extra.pop("url", None),
        "location": extra.pop("location", "Chennai"),
        "remote_type": extra.pop("remote_type", None),
        "employment_type": extra.pop("employment_type", None),
        "salary": extra.pop("salary", None),
        "description": extra.pop("description", "desc"),
        "requirements": extra.pop("requirements", []),
        "skills": extra.pop("skills", []),
        "application_url": extra.pop("application_url", None),
        "company_url": extra.pop("company_url", None),
        "posted_date": extra.pop("posted_date", None),
        **extra,
    }


def _seed(session, rows):
    """Insert rows through the fixture session so they roll back with it."""
    stmt = text(
        "INSERT INTO jobs "
        "(title, company, location, remote_type, source, source_job_id, url, requirements, skills) "
        "VALUES "
        "(:title,:company,:location,:remote_type,'apify',:source_job_id,:url,'[]'::jsonb,'[]'::jsonb)"
    )
    session.execute(stmt, rows)
    session.commit()


def _row(title, company, location, key, url, remote_type=None):
    return {
        "title": title,
        "company": company,
        "location": location,
        "remote_type": remote_type,
        "source_job_id": key,
        "url": url,
    }


def test_list_jobs_empty_returns_pagination(client_db):
    client, _ = client_db
    response = client.get("/jobs?page=1&limit=20")
    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "limit": 20, "total": 0, "pages": 0}


def test_list_jobs_filters_and_pagination(client_db):
    client, session = client_db
    _seed(session, [
        _row("Software Developer", "Acme", "Chennai", _next_key("flt"),
             "https://x.test/1", "hybrid"),
        _row("Backend Developer", "Beta", "Madurai", _next_key("flt"),
             "https://x.test/2", "remote"),
        _row("Frontend Developer", "Gamma", "Chennai", _next_key("flt"),
             "https://x.test/3", "onsite"),
    ])

    body = client.get("/jobs?limit=2").json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2

    assert client.get("/jobs?location=Chennai").json()["total"] == 2
    assert client.get("/jobs?role=Software").json()["total"] == 1
    assert client.get("/jobs?remote_type=remote").json()["total"] == 1
    assert client.get("/jobs?source=apify").json()["total"] == 3
    assert client.get("/jobs?role=Frontend").json()["total"] == 1
    assert client.get("/jobs?role=missing-role").json()["total"] == 0


def test_get_job_detail_and_404(client_db):
    client, session = client_db
    assert client.get("/jobs/999999").status_code == 404

    _seed(session, [
        _row("Software Developer", "Acme", "Chennai", _next_key("det"), "https://x.test/1"),
    ])
    target = client.get("/jobs?limit=100").json()["items"][0]
    detail = client.get(f"/jobs/{target['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Software Developer"
    assert detail.json()["company"] == "Acme"


def test_insert_dedup_by_source_job_id(client_db):
    client, session = client_db
    key = _next_key("dup1")
    from app.services import job_service

    jobs = [
        _build_job("Software Developer", "Acme", source_job_id=key, url="https://x.test/1"),
        _build_job("Software Developer", "Acme", source_job_id=key, url="https://x.test/1"),
        _build_job("Backend Developer", "Beta", source_job_id=_next_key("dup1"), url="https://x.test/2"),
    ]
    result = job_service.insert_jobs(session, jobs, source="apify")
    assert result.inserted == 2
    assert result.duplicates == 1
    assert client.get("/jobs").json()["total"] == 2


def test_insert_dedup_by_url_without_key(client_db):
    client, session = client_db
    from app.services import job_service

    jobs = [
        _build_job("Software Developer", "Acme", url="https://x.test/url1"),
        _build_job("Software Developer", "Acme", url="https://x.test/url1"),
    ]
    result = job_service.insert_jobs(session, jobs, source="apify")
    assert result.inserted == 1
    assert result.duplicates == 1


def test_insert_dedup_by_triplet(client_db):
    client, session = client_db
    from app.services import job_service

    jobs = [
        _build_job("Software Developer", "Acme Corp", location="Chennai, Tamil Nadu"),
        _build_job("Software Developer", "Acme Corp", location="Chennai, Tamil Nadu"),
        _build_job("Software Developer", "Acme Corp", location="Madurai"),
    ]
    result = job_service.insert_jobs(session, jobs, source="apify")
    assert result.inserted == 2
    assert result.duplicates == 1


def test_search_request_validation(client_db):
    client, _ = client_db
    assert client.post("/jobs/search", json={"limit": 0}).status_code == 422
    assert client.post("/jobs/search", json={"limit": 500}).status_code == 422


def test_start_search_creates_run(client_db):
    client, session = client_db
    from sqlalchemy import select

    from app.models.automation import AutomationRun

    body = client.post("/jobs/search", json={"limit": 10}).json()
    assert body["status"] == "started"
    assert isinstance(body.get("run_id"), int)
    run = session.scalar(select(AutomationRun).where(AutomationRun.id == body["run_id"]))
    assert run is not None
    assert run.status == "RUNNING"
    assert run.job_source == "apify"
    assert client.get(f"/jobs/runs/{body['run_id']}").json()["status"] == "RUNNING"


@pytest.fixture
def patched_source(monkeypatch):
    from app.services import search_service

    def _patch(fake_search):
        fake = type("Fake", (), {})()
        fake.search_jobs = fake_search  # instance attribute: no descriptor binding
        monkeypatch.setattr(search_service, "_get_source", lambda name: fake)
        return fake

    return _patch


def test_run_discovery_logs_partial(client_db, patched_source):
    client, session = client_db
    from app.services import automation_service as run_log
    from app.services import search_service

    def fake_search(preferences, limit=None):
        return _scrape_result(
            jobs=[
                _build_job("Software Developer", "Acme", source_job_id=_next_key("run"), url="https://x.test/10"),
                _build_job("Backend Developer", "Beta", source_job_id=_next_key("run"), url="https://x.test/11"),
                _build_job("Frontend Developer", "Gamma", source_job_id=_next_key("run"), url="https://x.test/12"),
            ],
            invalid=[{"record": {"title": "", "company": "NoTitleCo"}, "reason": "missing title"}],
            raw_count=4,
        )

    patched_source(fake_search)

    run = run_log.start_run(session, run_type="job_search", source="apify")
    completed = search_service.run_discovery(session, run.id)

    assert completed is not None
    assert run_log.get_run(session, run.id).status == "PARTIAL"
    body = client.get(f"/jobs/runs/{run.id}").json()
    assert body["status"] == "PARTIAL"
    assert body["jobs_found"] == 4
    assert body["jobs_processed"] == 3
    assert body["details"]["inserted"] == 3
    assert body["details"]["duplicates"] == 0
    assert body["details"]["invalid"] == 1
    assert client.get("/jobs").json()["total"] == 3

    assert client.get("/jobs/runs/999999").status_code == 404


def test_run_discovery_duplicates_second_run(client_db, patched_source):
    client, session = client_db
    from app.services import automation_service as run_log
    from app.services import search_service

    k1, k2 = _next_key("dbl"), _next_key("dbl")

    def fake_search(preferences, limit=None):
        return _scrape_result(
            jobs=[
                _build_job("Software Developer", "Acme", source_job_id=k1, url="https://x.test/20"),
                _build_job("Backend Developer", "Beta", source_job_id=k2, url="https://x.test/21"),
            ],
            raw_count=2,
        )

    patched_source(fake_search)

    run1 = run_log.start_run(session, run_type="job_search", source="apify")
    search_service.run_discovery(session, run1.id)
    run2 = run_log.start_run(session, run_type="job_search", source="apify")
    search_service.run_discovery(session, run2.id)

    first = client.get(f"/jobs/runs/{run1.id}").json()
    second = client.get(f"/jobs/runs/{run2.id}").json()
    assert first["details"]["inserted"] == 2
    assert first["details"]["duplicates"] == 0
    assert second["details"]["inserted"] == 0
    assert second["details"]["duplicates"] == 2
    assert client.get("/jobs").json()["total"] == 2


def test_run_discovery_failure_logs_run(client_db, patched_source):
    client, session = client_db
    from app.services import automation_service as run_log
    from app.services import search_service

    def boom(preferences, limit=None):
        raise RuntimeError("actor exploded")

    patched_source(boom)

    run = run_log.start_run(session, run_type="job_search", source="apify")
    search_service.run_discovery(session, run.id)

    body = client.get(f"/jobs/runs/{run.id}").json()
    assert body["status"] == "FAILED"
    assert body["details"]["message"] == "Search failed: actor exploded"
    assert client.get("/jobs").json()["total"] == 0
