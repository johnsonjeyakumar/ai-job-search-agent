from typing import Type

from app.job_sources.base import JobSource


class JobSourceRegistry:
    """Registry so sources can be registered and looked up by name."""

    def __init__(self) -> None:
        self._sources: dict[str, Type[JobSource]] = {}

    def register(self, source: Type[JobSource]) -> None:
        self._sources[source.name] = source

    def get(self, name: str) -> Type[JobSource] | None:
        return self._sources.get(name)

    def available(self) -> list[str]:
        return list(self._sources)


job_source_registry = JobSourceRegistry()
