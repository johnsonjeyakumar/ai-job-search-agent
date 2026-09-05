"""Abstract job-discovery source.

Every concrete source (Apify actors, public REST APIs, ...) implements the
same small interface so the pipeline (search -> normalize -> validate ->
deduplicate -> persist) stays provider-independent.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class JobSourceError(Exception):
    """Raised when a job source cannot complete a search."""


@dataclass
class ScrapeResult:
    """Outcome of one discovery run against a job source."""

    source: str
    raw_count: int = 0
    jobs: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class JobSource(ABC):
    """Source-agnostic job discovery interface."""

    name: str = "base"

    @abstractmethod
    def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute a provider search and return raw records."""

    @abstractmethod
    def normalize_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Convert one raw record into a JobCreate-shaped dictionary."""

    @abstractmethod
    def validate_job(self, normalized: dict[str, Any]) -> tuple[bool, str]:
        """Return ``(ok, reason)`` describing whether a normalized job is usable."""

    def search_jobs(
        self,
        preferences: dict[str, Any],
        limit: int | None = None,
    ) -> ScrapeResult:
        """Search, normalize, and validate in one call.

        Normalized records are already trimmed to the request limit. Invalid
        records are collected (with reasons) so a single bad record never
        aborts the whole import.
        """
        params = self.build_search_params(preferences, limit)
        raw = self.search(params)
        raw = list(raw)[: self._effective_limit(limit)]
        valid: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        for record in raw:
            normalized = self.normalize_job(record)
            normalized["source"] = self.name
            ok, reason = self.validate_job(normalized)
            if ok:
                valid.append(normalized)
            else:
                invalid.append({"record": normalized, "reason": reason})
        return ScrapeResult(
            source=self.name,
            raw_count=len(raw),
            jobs=valid,
            invalid=invalid,
            params=params,
        )

    def build_search_params(
        self, preferences: dict[str, Any], limit: int | None = None
    ) -> dict[str, Any]:
        """Convert stored preferences into source-specific search parameters."""
        return {"preferences": preferences, "limit": limit}

    def _effective_limit(self, limit: int | None) -> int:
        return max(1, limit or 64)
