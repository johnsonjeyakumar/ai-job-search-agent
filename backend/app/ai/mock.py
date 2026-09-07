from typing import Any

from app.ai.base import AIProvider


class MockAIProvider(AIProvider):
    """No-op provider used before a real AI provider is configured."""

    name = "mock"

    async def analyze_job(self, job: Any, profile: Any) -> dict[str, Any]:
        return {
            "provider": self.name,
            "analyzed": False,
            "reason": "AI analysis is not configured yet.",
        }

    async def generate_cover_letter(self, job: Any, profile: Any, resume: Any) -> str:
        return ""

    async def answer_question(self, job: Any, profile: Any, question: str) -> str:
        return ""

    async def extract_job_requirements(self, job: Any) -> dict[str, Any] | None:
        return None

    async def draft_cover_letter(self, job: Any, profile: Any, resume: Any) -> dict | None:
        return None

    async def draft_application_answers(
        self, job: Any, profile: Any, resume: Any, questions: list[dict[str, str]]
    ) -> list[dict] | None:
        return None

    async def suggest_tailoring(
        self, job: Any, profile: Any, resume: Any, gaps: list[dict[str, Any]]
    ) -> list[dict] | None:
        return None

    async def validate_application(
        self, job: Any, profile: Any, resume: Any, package: dict[str, Any]
    ) -> list[dict] | None:
        return None

    async def generate_interview_questions(
        self, job: Any, profile: Any, resume: Any, categories: list[str], count: int
    ) -> list[dict] | None:
        return None

    async def evaluate_interview_answer(
        self, question: str, answer: str, category: str
    ) -> dict | None:
        return None

    async def generate_interview_prep_summary(
        self, job: Any, profile: Any, interview_context: dict[str, Any]
    ) -> str | None:
        return None
