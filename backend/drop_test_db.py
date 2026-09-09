"""Drop the test database to reset schema."""
from sqlalchemy import create_engine, make_url, text
from app.config.settings import get_settings
import app.models  # noqa: F401

settings = get_settings()
url = make_url(settings.database_url).set(database='postgres').render_as_string(hide_password=False)
admin = create_engine(url, isolation_level='AUTOCOMMIT')

with admin.connect() as conn:
    exists = conn.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :name"), {'name': 'job_agent_test'}
    ).scalar()
    if exists:
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'job_agent_test'"))
        conn.execute(text('DROP DATABASE IF EXISTS job_agent_test'))
        print('Dropped existing test database')
    else:
        print('Test database does not exist')

admin.dispose()
print('Done')
