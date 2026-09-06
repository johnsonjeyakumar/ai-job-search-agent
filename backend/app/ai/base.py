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

    # -- Phase 6: application preparation ------------------------------------

    @abstractmethod
    async def draft_cover_letter(
        self, job: Any, profile: Any, resume: Any
    ) -> dict[str, Any] | None:
        """Draft a cover-letter body ({'text': ...}) or ``None``.

        The caller validates the response against ``AICoverLetter`` and falls
        back deterministically; the LLM never decides the quality gate.
        """

    @abstractmethod
    async def draft_application_answers(
        self,
        job: Any,
        profile: Any,
        resume: Any,
        questions: list[dict[str, str]],
    ) -> list[dict[str, Any]] | None:
        """Draft answers for application questions, or ``None``.

        Response items are validated against ``AIApplicationAnswer``; invalid
        or score-tainted output is rejected and replaced deterministically.
        """

    @abstractmethod
    async def suggest_tailoring(
        self,
        job: Any,
        profile: Any,
        resume: Any,
        gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Suggest resume tailoring wording for gaps, or ``None``.

        Response items are validated against ``AITailoringSuggestion``; the
        deterministic fallback never invents new facts.
        """

    @abstractmethod
    async def validate_application(
        self,
        job: Any,
        profile: Any,
        resume: Any,
        package: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Return truth/consistency findings, or ``None``.

        Findings are validated against ``AIValidationFinding``; they never
        alter scores or protected profile facts.
        """
