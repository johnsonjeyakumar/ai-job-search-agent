from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Base class for future agents (discovery, analysis, application).

    Agents orchestrate one concern end-to-end and record progress in
    ``automation_runs`` / ``automation_errors``.
    """

    name: str = "base"

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent's workflow and return a result summary."""
