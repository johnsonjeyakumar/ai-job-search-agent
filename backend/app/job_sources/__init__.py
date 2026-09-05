"""Job discovery sources. Importing this package registers built-in sources."""
from app.job_sources.apify import ApifyJobSource
from app.job_sources.base import JobSource, JobSourceError, ScrapeResult
from app.job_sources.registry import job_source_registry

job_source_registry.register(ApifyJobSource)

__all__ = [
    "ApifyJobSource",
    "JobSource",
    "JobSourceError",
    "ScrapeResult",
    "job_source_registry",
]
