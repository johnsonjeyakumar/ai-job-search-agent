from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """Abstract AI provider.

    Concrete providers (OpenAI, Anthropic, Gemini, local models, ...) implement
    this interface so the backend never depends on a specific vendor. Select
    the active provider via the ``AI_PROVIDER`` setting.
    """

    name: str = "base"

    @abstractmethod
    async def analyze_job(self, job: Any, profile: Any) -> dict[str, Any]:
        """Return a match analysis for a job against a profile."""

    @abstractmethod
    async def generate_cover_letter(self, job: Any, profile: Any, resume: Any) -> str:
        """Generate a tailored cover letter."""

    @abstractmethod
    async def answer_question(self, job: Any, profile: Any, question: str) -> str:
        """Answer an application question using the profile."""

    @abstractmethod
    async def extract_job_requirements(self, job: Any) -> dict[str, Any] | None:
        """Extract structured job requirements from unstructured text.

        Providers return ``None`` when they cannot contribute; the caller then
        falls back to the deterministic extractor.
        """
