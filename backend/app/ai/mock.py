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
