from sqlalchemy import text

EXPECTED_TABLES = {
    "profiles",
    "resumes",
    "jobs",
    "job_matches",
    "applications",
    "recruiter_contacts",
    "follow_ups",
    "automation_runs",
    "automation_errors",
}


def test_database_connection(db_engine):
    with db_engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_schema_migrated(db_engine):
    """All tables from the initial Alembic migration must exist."""
    with db_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    tables = {row[0] for row in rows}
    assert EXPECTED_TABLES.issubset(tables), f"Missing tables: {EXPECTED_TABLES - tables}"
