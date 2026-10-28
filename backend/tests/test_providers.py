import asyncio
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers.base import (
    GenerationRequest,
    InvalidProviderResponseError,
    ModelNotFoundError,
    ModelUnavailableError,
    ProviderMessage,
    ProviderTimeoutError,
)
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


def generation_request() -> GenerationRequest:
    return GenerationRequest(
        messages=(
            ProviderMessage(role="system", content="Be concise."),
            ProviderMessage(role="user", content="Hello"),
        ),
        model="test-model",
        max_output_tokens=64,
    )


def create_provider() -> OllamaProvider:
    return OllamaProvider(
        base_url="http://127.0.0.1:11434/",
        model="local-model",
        connect_timeout_seconds=2,
        read_timeout_seconds=5,
    )


def ollama_response(lines: list[str], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.iter_lines.return_value = lines
    response.json.return_value = {}
    context = MagicMock()
    context.__enter__.return_value = response
    return context


def test_mock_provider_is_deterministic_for_generate_and_stream() -> None:
    provider = MockProvider()
    request = generation_request()

    streamed = list(provider.stream(request))

    assert "".join(streamed) == provider.generate(request)
    assert "".join(streamed) == "Mock response: Hello"
    assert len(streamed) > 1
    assert provider.supports_embeddings is False


def test_ollama_stream_formats_model_history_and_output_limit() -> None:
    context = ollama_response(
        [
            json.dumps({"message": {"content": "Hello "}, "done": False}),
            json.dumps({"message": {"content": "there"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
    )
    with patch("app.providers.ollama.httpx.stream", return_value=context) as stream:
        response = "".join(create_provider().stream(generation_request()))

    assert response == "Hello there"
    args, kwargs = stream.call_args
    assert args == ("POST", "http://127.0.0.1:11434/api/chat")
    assert kwargs["json"] == {
        "model": "local-model",
        "stream": True,
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ],
        "options": {"num_predict": 64},
    }
    assert kwargs["timeout"].connect == 2
    assert kwargs["timeout"].read == 5


def test_ollama_async_stream_emits_chunks_incrementally() -> None:
    request_payloads: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        request_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=(
                b'{"message":{"content":"real "},"done":false}\n'
                b'{"message":{"content":"answer"},"done":false}\n'
                b'{"message":{"content":""},"done":true}\n'
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def collect() -> list[str]:
        with patch("app.providers.ollama.httpx.AsyncClient", return_value=client):
            return [
                chunk
                async for chunk in create_provider().astream(generation_request())
            ]

    chunks = asyncio.run(collect())

    assert chunks == ["real ", "answer"]
    assert request_payloads[0]["stream"] is True
    assert request_payloads[0]["model"] == "local-model"


def test_cancelling_ollama_async_stream_closes_response() -> None:
    class GatedStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False
            self.release = asyncio.Event()

        async def __aiter__(self):
            yield b'{"message":{"content":"first"},"done":false}\n'
            await self.release.wait()
            yield b'{"message":{"content":"","done":true}}\n'

        async def aclose(self) -> None:
            self.closed = True

    response_stream = GatedStream()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=response_stream)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def cancel_after_first_chunk() -> str:
        with patch("app.providers.ollama.httpx.AsyncClient", return_value=client):
            stream = create_provider().astream(generation_request())
            first = await anext(stream)
            pending = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await stream.aclose()
            return first

    assert asyncio.run(cancel_after_first_chunk()) == "first"
    assert response_stream.closed is True


def test_ollama_generate_uses_non_streaming_chat_response() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "message": {"role": "assistant", "content": "A real answer."},
        "done": True,
    }

    with patch("app.providers.ollama.httpx.post", return_value=response) as post:
        result = create_provider().generate(generation_request())

    assert result == "A real answer."
    assert post.call_args.kwargs["json"]["stream"] is False
    assert post.call_args.kwargs["json"]["messages"][0] == {
        "role": "system",
        "content": "Be concise.",
    }
    assert post.call_args.kwargs["timeout"].connect == 2


def test_ollama_reports_model_not_found_without_exposing_provider_details() -> None:
    context = ollama_response([], status_code=404)
    context.__enter__.return_value.json.return_value = {
        "error": "model 'secret-internal-tag' not found, try pulling it first"
    }
    with patch("app.providers.ollama.httpx.stream", return_value=context):
        with pytest.raises(ModelNotFoundError) as error:
            list(create_provider().stream(generation_request()))

    assert "secret-internal-tag" not in error.value.public_message


def test_ollama_stream_error_chunk_and_missing_completion_are_rejected() -> None:
    error_context = ollama_response(
        [json.dumps({"error": "model 'local-model' not found"})]
    )
    with patch("app.providers.ollama.httpx.stream", return_value=error_context):
        with pytest.raises(ModelNotFoundError):
            list(create_provider().stream(generation_request()))

    incomplete_context = ollama_response(
        [json.dumps({"message": {"content": "partial"}, "done": False})]
    )
    with patch("app.providers.ollama.httpx.stream", return_value=incomplete_context):
        with pytest.raises(InvalidProviderResponseError):
            list(create_provider().stream(generation_request()))


def test_ollama_connection_failure_timeout_and_malformed_response_are_typed() -> None:
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    with patch(
        "app.providers.ollama.httpx.stream",
        side_effect=httpx.ConnectError("refused", request=request),
    ):
        with pytest.raises(ModelUnavailableError):
            list(create_provider().stream(generation_request()))

    with patch(
        "app.providers.ollama.httpx.stream",
        side_effect=httpx.ReadTimeout("timeout", request=request),
    ):
        with pytest.raises(ProviderTimeoutError):
            list(create_provider().stream(generation_request()))

    with patch(
        "app.providers.ollama.httpx.stream",
        return_value=ollama_response(["not-json"]),
    ):
        with pytest.raises(InvalidProviderResponseError):
            list(create_provider().stream(generation_request()))


def test_ollama_availability_reports_selected_local_model() -> None:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "local-model:latest"}]}
    with patch("app.providers.ollama.httpx.get", return_value=response):
        assert create_provider().is_available() is True

    with patch(
        "app.providers.ollama.httpx.get",
        side_effect=httpx.ConnectError(
            "offline",
            request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
        ),
    ):
        assert create_provider().is_available() is False
