import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (register all tables on Base.metadata)
from app.config.settings import get_settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app as fastapi_app

TEST_DB_NAME = "job_agent_test"


def _admin_engine():
    url = make_url(get_settings().database_url)
    return create_engine(_url_for_db(url, "postgres"), isolation_level="AUTOCOMMIT")


def _url_for_db(url, db_name):
    if url.drivername.startswith("postgresql"):
        return url.set(database=db_name).render_as_string(hide_password=False)
    if url.drivername == "sqlite":
        return url.render_as_string(hide_password=False)
    raise RuntimeError(f"Unsupported database driver for test isolation: {url.drivername}")


@pytest.fixture(scope="session", autouse=True)
def isolated_test_db():
    """Create a dedicated test database and a clean schema once per session."""
    settings = get_settings()
    admin = _admin_engine()
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()

    engine = create_engine(_url_for_db(make_url(settings.database_url), TEST_DB_NAME))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{TEST_DB_NAME}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db_engine():
    settings = get_settings()
    test_url = _url_for_db(make_url(settings.database_url), TEST_DB_NAME)
    return create_engine(test_url, pool_pre_ping=True)


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_engine):
    """TestClient whose DB writes are wrapped in a rolled-back transaction."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    def override_get_db():
        try:
            yield session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.pop(get_db, None)
    session.close()
    transaction.rollback()
    connection.close()
