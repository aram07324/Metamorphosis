import json
from collections.abc import AsyncIterator, Iterator
from typing import NoReturn

import httpx

from app.providers.base import (
    AIProvider,
    GenerationRequest,
    InvalidProviderResponseError,
    ModelNotFoundError,
    ModelUnavailableError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = httpx.Timeout(
            read_timeout_seconds,
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        try:
            response = httpx.get(
                f"{self._base_url}/api/tags",
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return False
        models = payload.get("models", []) if isinstance(payload, dict) else []
        if not isinstance(models, list):
            return False
        return any(
            isinstance(model, dict)
            and model.get("name") in {self._model, f"{self._model}:latest"}
            for model in models
        )

    def generate(self, request: GenerationRequest) -> str:
        try:
            response = httpx.post(
                f"{self._base_url}/api/chat",
                json=self._payload(request, stream=False),
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                _raise_response_error(response.status_code, _response_payload(response))
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.ConnectError as exc:
            raise ModelUnavailableError() from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError() from exc
        except ValueError as exc:
            raise InvalidProviderResponseError() from exc

        if not isinstance(payload, dict):
            raise InvalidProviderResponseError()
        if "error" in payload:
            _raise_payload_error(payload)
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or payload.get("done") is not True:
            raise InvalidProviderResponseError()
        if not content:
            raise InvalidProviderResponseError()
        return content

    def stream(self, request: GenerationRequest) -> Iterator[str]:
        try:
            with httpx.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=self._payload(request, stream=True),
                timeout=self._timeout,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    _raise_response_error(
                        response.status_code,
                        _response_payload(response),
                    )

                completed = False
                for line in response.iter_lines():
                    if not line:
                        continue
                    content, done = _parse_stream_line(line)
                    if content:
                        yield content
                    if done:
                        completed = True
                        break
                if not completed:
                    raise InvalidProviderResponseError()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.ConnectError as exc:
            raise ModelUnavailableError() from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError() from exc

    async def astream(self, request: GenerationRequest) -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/chat",
                    json=self._payload(request, stream=True),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        _raise_response_error(
                            response.status_code,
                            _response_payload(response),
                        )

                    completed = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        content, done = _parse_stream_line(line)
                        if content:
                            yield content
                        if done:
                            completed = True
                            break
                    if not completed:
                        raise InvalidProviderResponseError()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except httpx.ConnectError as exc:
            raise ModelUnavailableError() from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError() from exc

    def _payload(self, request: GenerationRequest, *, stream: bool) -> dict[str, object]:
        return {
            "model": self._model,
            "stream": stream,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "options": {"num_predict": request.max_output_tokens},
        }


def _response_payload(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_stream_line(line: str) -> tuple[str, bool]:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise InvalidProviderResponseError() from exc
    if not isinstance(data, dict):
        raise InvalidProviderResponseError()
    if "error" in data:
        _raise_payload_error(data)

    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    done = data.get("done")
    if not isinstance(content, str) or not isinstance(done, bool):
        raise InvalidProviderResponseError()
    return content, done


def _raise_response_error(status_code: int, payload: dict[str, object]) -> NoReturn:
    if status_code == 429:
        raise ProviderRateLimitError()
    if "error" in payload:
        _raise_payload_error(payload)
    if status_code == 404 or status_code >= 500:
        raise ModelUnavailableError()
    raise InvalidProviderResponseError()


def _raise_payload_error(payload: dict[str, object]) -> NoReturn:
    error = payload.get("error")
    if isinstance(error, str):
        normalized_error = error.lower()
        if "model" in normalized_error and "not found" in normalized_error:
            raise ModelNotFoundError()
    raise InvalidProviderResponseError()
