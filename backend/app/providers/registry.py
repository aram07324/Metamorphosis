from collections.abc import Callable

from app.core.config import Settings
from app.providers.base import AIProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider

ProviderFactory = Callable[[Settings], AIProvider]


def _mock_provider(_: Settings) -> AIProvider:
    return MockProvider()


def _ollama_provider(settings: Settings) -> AIProvider:
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        connect_timeout_seconds=settings.provider_connect_timeout_seconds,
        read_timeout_seconds=settings.provider_timeout_seconds,
    )


PROVIDER_REGISTRY: dict[str, ProviderFactory] = {
    "mock": _mock_provider,
    "ollama": _ollama_provider,
}


def create_provider(settings: Settings) -> AIProvider:
    try:
        factory = PROVIDER_REGISTRY[settings.ai_provider]
    except KeyError as exc:
        raise ValueError(f"Unknown AI provider: {settings.ai_provider}") from exc
    return factory(settings)
