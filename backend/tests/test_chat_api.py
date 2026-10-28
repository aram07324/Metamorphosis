import asyncio
import json
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from app.api.chat import stream_message
from app.core.config import Settings
from app.db.session import create_database_engine
from app.main import create_app
from app.models.chat import ChatTurn
from app.providers.base import ModelNotFoundError, ModelUnavailableError, ProviderMessage
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider
from app.schemas.chat import SendMessageRequest


def create_conversation(client: TestClient) -> str:
    response = client.post("/api/v1/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in body.replace("\r\n", "\n").split("\n\n"):
        event_name = "message"
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def send_message(
    client: TestClient,
    conversation_id: str,
    key: str = "request-0001",
    content: str = "Hello, assistant!",
):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/messages/stream",
        json={"content": content},
        headers={"Idempotency-Key": key},
    )


def test_mock_chat_stream_persists_conversation_and_messages(client: TestClient) -> None:
    conversation_id = create_conversation(client)
    response = send_message(client, conversation_id)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"].startswith("no-cache")
    events = parse_sse(response.text)
    assert events[0][0] == "meta"
    assert events[-1][0] == "done"
    delta_events = [payload for event, payload in events if event == "delta"]
    assert len(delta_events) > 1
    assert "".join(
        payload["delta"] for event, payload in events if event == "delta"
    ) == "Mock response: Hello, assistant!"
    done_payload = events[-1][1]
    assert done_payload["context"]["input_budget_tokens"] == 3584

    conversation = client.get(f"/api/v1/conversations/{conversation_id}")
    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert conversation.json()["title"] == "Hello, assistant!"
    assert [message["role"] for message in messages.json()["items"]] == [
        "user",
        "assistant",
    ]
    assert messages.json()["items"][1]["content"] == "Mock response: Hello, assistant!"


def test_completed_idempotency_key_replays_without_duplicate_messages(
    client: TestClient,
) -> None:
    conversation_id = create_conversation(client)
    first = send_message(client, conversation_id)
    replay = send_message(client, conversation_id)

    assert first.status_code == replay.status_code == 200
    replay_events = parse_sse(replay.text)
    assert replay_events[-1][1]["replayed"] is True
    assert len(client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]) == 2


def test_failed_provider_response_is_reported_and_same_turn_can_retry(
    client: TestClient,
) -> None:
    class FailingProvider(MockProvider):
        name = "failing"

        def stream(self, request):
            raise ModelUnavailableError()
            yield ""

    conversation_id = create_conversation(client)
    client.app.state.ai_provider = FailingProvider()
    failed = send_message(client, conversation_id, key="retry-key-01")
    failed_events = parse_sse(failed.text)

    assert failed.status_code == 200
    assert failed_events[-1][0] == "error"
    assert failed_events[-1][1]["error"]["code"] == "model_unavailable"
    assert len(client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]) == 1

    client.app.state.ai_provider = MockProvider()
    retried = send_message(client, conversation_id, key="retry-key-01")
    assert parse_sse(retried.text)[-1][0] == "done"
    assert len(client.get(f"/api/v1/conversations/{conversation_id}/messages").json()["items"]) == 2


def test_retry_does_not_duplicate_the_user_prompt_in_provider_context(
    client: TestClient,
) -> None:
    class CaptureProvider(MockProvider):
        messages = ()
        fail_next = True

        def stream(self, request):
            self.messages = request.messages
            if self.fail_next:
                self.fail_next = False
                raise ModelUnavailableError()
                yield ""
            yield from super().stream(request)

    conversation_id = create_conversation(client)
    client.app.state.ai_provider = CaptureProvider()
    send_message(client, conversation_id, key="retry-context-01")
    send_message(client, conversation_id, key="retry-context-01")

    user_messages = [
        message.content
        for message in client.app.state.ai_provider.messages
        if message.role == "user"
    ]
    assert user_messages == ["Hello, assistant!"]


def test_context_includes_previous_turns_and_isolated_to_active_conversation(
    client: TestClient,
) -> None:
    first_conversation_id = create_conversation(client)
    other_conversation_id = create_conversation(client)
    send_message(
        client,
        first_conversation_id,
        key="first-turn-001",
        content="Remember my color is blue.",
    )
    send_message(
        client,
        other_conversation_id,
        key="other-turn-001",
        content="Do not include this private conversation.",
    )

    class CaptureProvider(MockProvider):
        messages: tuple[ProviderMessage, ...] = ()

        def stream(self, request):
            self.messages = request.messages
            yield "The color is blue."

    provider = CaptureProvider()
    client.app.state.ai_provider = provider
    response = send_message(
        client,
        first_conversation_id,
        key="second-turn-001",
        content="What color did I mention?",
    )

    assert response.status_code == 200
    assert provider.messages == (
        ProviderMessage(
            role="system",
            content=client.app.state.settings.chat_system_prompt,
        ),
        ProviderMessage(role="user", content="Remember my color is blue."),
        ProviderMessage(role="assistant", content="Mock response: Remember my color is blue."),
        ProviderMessage(role="user", content="What color did I mention?"),
    )
    assert all(
        "private conversation" not in message.content for message in provider.messages
    )


def test_chat_system_prompt_supports_technical_and_authorized_security_work() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider="mock",
        cors_origins=["http://localhost:3000"],
    )
    prompt = settings.chat_system_prompt
    assert "software development" in prompt.lower()
    assert "authorized security work" in prompt.lower()
    assert "moralizing" in prompt.lower()


def test_selected_ollama_unavailable_does_not_fall_back_to_mock(
    client: TestClient,
) -> None:
    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="local-model",
        connect_timeout_seconds=1,
        read_timeout_seconds=5,
    )
    client.app.state.ai_provider = provider
    conversation_id = create_conversation(client)
    with patch(
        "app.providers.ollama.httpx.get",
        side_effect=httpx.ConnectError(
            "connection refused",
            request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
        ),
    ):
        provider_status = client.get("/api/v1/chat/provider")
    assert provider_status.json() == {
        "provider": "ollama",
        "model": "local-model",
        "configured": True,
        "available": False,
    }

    def fail_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async_client_factory = httpx.AsyncClient
    with patch(
        "app.providers.ollama.httpx.AsyncClient",
        side_effect=lambda *args, **kwargs: async_client_factory(
            transport=httpx.MockTransport(fail_connection),
            **kwargs,
        ),
    ):
        response = send_message(
            client,
            conversation_id,
            key="ollama-down-001",
        )

    error_event = parse_sse(response.text)[-1]
    assert error_event[0] == "error"
    assert error_event[1]["error"]["code"] == "model_unavailable"
    assert "Ollama service" in error_event[1]["error"]["message"]
    assert "Mock response" not in response.text


def test_app_starts_with_ollama_selected_when_service_is_not_installed() -> None:
    settings = Settings(_env_file=None, ai_provider="ollama")
    engine = create_database_engine("sqlite:///:memory:")

    with TestClient(create_app(settings=settings, engine=engine)) as ollama_client:
        assert ollama_client.get("/api/v1/health").status_code == 200
        with patch(
            "app.providers.ollama.httpx.get",
            side_effect=httpx.ConnectError(
                "offline",
                request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
            ),
        ):
            provider_status = ollama_client.get("/api/v1/chat/provider")

    assert provider_status.status_code == 200
    assert provider_status.json()["provider"] == "ollama"
    assert provider_status.json()["available"] is False


def test_missing_ollama_model_is_recoverable_and_not_persisted_as_reply(
    client: TestClient,
) -> None:
    conversation_id = create_conversation(client)

    class MissingModelProvider(OllamaProvider):
        name = "ollama"

        async def astream(self, request):
            raise ModelNotFoundError()
            yield ""

    client.app.state.ai_provider = MissingModelProvider(
        base_url="http://127.0.0.1:11434",
        model="local-model",
        connect_timeout_seconds=1,
        read_timeout_seconds=5,
    )
    response = send_message(
        client,
        conversation_id,
        key="ollama-missing-001",
    )
    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages"
    ).json()["items"]

    assert parse_sse(response.text)[-1][1]["error"]["code"] == "model_not_found"
    assert [message["role"] for message in messages] == ["user"]

def test_closing_sse_stream_marks_turn_cancelled(client: TestClient) -> None:
    conversation_id = create_conversation(client)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat",
        "raw_path": b"/api/v1/chat",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "app": client.app,
    }
    response = stream_message(
        Request(scope),
        conversation_id,
        SendMessageRequest(content="Cancel this response"),
        "cancel-request-01",
    )

    async def close_stream() -> str:
        iterator = response.body_iterator
        first_event = await iterator.__anext__()
        await iterator.aclose()
        return first_event

    assert "event: meta" in asyncio.run(close_stream())
    with client.app.state.session_factory() as session:
        turn = session.scalar(select(ChatTurn))
        assert turn is not None
        assert turn.status == "cancelled"


def test_chat_validation_and_idempotency_conflicts_are_consistent(
    client: TestClient,
) -> None:
    conversation_id = create_conversation(client)
    invalid_key = send_message(client, conversation_id, key="short")
    assert invalid_key.status_code == 422
    assert invalid_key.json()["error"]["code"] == "invalid_idempotency_key"

    completed = send_message(client, conversation_id)
    assert completed.status_code == 200
    reused = send_message(
        client,
        conversation_id,
        content="Different body",
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "idempotency_key_reused"


def test_conversation_lifecycle_pagination_and_archive(client: TestClient) -> None:
    conversation_id = create_conversation(client)
    send_message(client, conversation_id)
    first_page = client.get(
        f"/api/v1/conversations/{conversation_id}/messages?limit=1"
    )
    assert first_page.json()["has_more"] is True
    assert first_page.json()["items"][0]["role"] == "user"

    renamed = client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Notes", "archived": True},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Notes"
    assert client.get("/api/v1/conversations").json()["total"] == 0
    assert client.get("/api/v1/conversations?include_archived=true").json()["total"] == 1

    archived_send = send_message(client, conversation_id, key="archived-01")
    assert archived_send.status_code == 409
    assert archived_send.json()["error"]["code"] == "conversation_archived"

    deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404


def test_validation_error_envelope_does_not_echo_input(client: TestClient) -> None:
    response = client.post("/api/v1/conversations", json={"title": " "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "input" not in response.json()["error"]["details"][0]


def test_chat_provider_defaults_to_mock(client: TestClient) -> None:
    response = client.get("/api/v1/chat/provider")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "mock",
        "model": "deterministic-mock",
        "configured": True,
        "available": True,
    }


def test_cors_preflight_allows_chat_idempotency_header(client: TestClient) -> None:
    response = client.options(
        "/api/v1/conversations",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


def test_turn_record_has_completion_status(client: TestClient) -> None:
    conversation_id = create_conversation(client)
    send_message(client, conversation_id)
    with client.app.state.session_factory() as session:
        turn = session.query(ChatTurn).one()
        assert turn.status == "completed"
        assert turn.completed_at is not None
