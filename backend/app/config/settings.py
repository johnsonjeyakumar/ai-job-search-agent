from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Job Search & Application Agent"
    app_version: str = "0.1.0"
    debug: bool = True

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/job_agent"
    )

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Abstract AI layer: "mock" is the only built-in provider in Phase 1.
    ai_provider: str = "mock"
    ai_model: str | None = None

    # Local file storage (resolved under PROJECT_ROOT). Swap with cloud storage later.
    upload_dir: str = "storage/resumes"
    max_upload_size_mb: int = 10

    # Apify job discovery
    apify_token: str = ""  # APIFY_TOKEN from environment / .env
    apify_actor_id: str = "schnellscrapers~indeed-jobs-scraper"
    apify_max_items: int = 20
    apify_run_timeout_secs: int = 300
    apify_poll_interval_secs: int = 5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_dir_abs(self) -> Path:
        return PROJECT_ROOT / self.upload_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
