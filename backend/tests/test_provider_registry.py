import pytest

from app.core.config import Settings
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider
from app.providers.registry import create_provider


def test_real_ollama_provider_is_the_default_without_startup_probe() -> None:
    settings = Settings(_env_file=None)

    provider = create_provider(settings)

    assert settings.ai_provider == "ollama"
    assert isinstance(provider, OllamaProvider)
    assert settings.ollama_model == "qwen2.5:3b"
    assert provider.model_name == "qwen2.5:3b"


def test_ollama_model_is_configurable_through_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "custom-local-model")

    settings = Settings(_env_file=None)
    provider = create_provider(settings)

    assert provider.model_name == "custom-local-model"


def test_mock_provider_remains_an_explicit_offline_option() -> None:
    provider = create_provider(Settings(_env_file=None, ai_provider="mock"))

    assert isinstance(provider, MockProvider)
