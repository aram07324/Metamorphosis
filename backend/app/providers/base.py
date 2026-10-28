import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass


class ProviderError(Exception):
    code = "provider_error"
    public_message = "The AI provider could not complete the request."


class ModelUnavailableError(ProviderError):
    code = "model_unavailable"
    public_message = (
        "The Ollama service or configured model is unavailable. Check that Ollama is "
        "running and OLLAMA_MODEL matches an installed model."
    )


class ModelNotFoundError(ProviderError):
    code = "model_not_found"
    public_message = (
        "The configured Ollama model is not installed. Check OLLAMA_MODEL against "
        "`ollama list`, then install that model before retrying."
    )


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    public_message = "The AI provider took too long to respond."


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limited"
    public_message = "The AI provider is temporarily rate limited."


class InvalidProviderResponseError(ProviderError):
    code = "invalid_provider_response"
    public_message = "The AI provider returned an invalid response."


@dataclass(frozen=True)
class ProviderMessage:
    role: str
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    messages: tuple[ProviderMessage, ...]
    model: str
    max_output_tokens: int


class AIProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, request: GenerationRequest) -> str:
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: GenerationRequest) -> Iterator[str]:
        raise NotImplementedError

    async def astream(self, request: GenerationRequest) -> AsyncIterator[str]:
        iterator = iter(self.stream(request))
        try:
            while True:
                has_item, item = await asyncio.to_thread(_next_item, iterator)
                if not has_item:
                    return
                if item:
                    yield item
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                await asyncio.to_thread(close)

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(f"{self.name} does not support embeddings.")

    def is_available(self) -> bool:
        return True

    @property
    def supports_embeddings(self) -> bool:
        return False

    @property
    def model_name(self) -> str:
        raise NotImplementedError


def _next_item(iterator: Iterator[str]) -> tuple[bool, str | None]:
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None
