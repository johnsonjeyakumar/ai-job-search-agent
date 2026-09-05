from typing import Type

from app.ai.base import AIProvider
from app.ai.mock import MockAIProvider
from app.config.settings import get_settings

_PROVIDERS: dict[str, Type[AIProvider]] = {
    "mock": MockAIProvider,
}


def get_provider() -> AIProvider:
    """Return the configured AI provider instance (defaults to mock)."""
    name = get_settings().ai_provider
    provider_class = _PROVIDERS.get(name, MockAIProvider)
    return provider_class()
