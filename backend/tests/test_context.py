import pytest

from app.providers.base import ProviderMessage
from app.services.context import build_context, estimate_tokens


def test_context_keeps_system_and_recent_history_within_budget() -> None:
    history = [
        ProviderMessage(role="user", content="old " * 80),
        ProviderMessage(role="assistant", content="older reply " * 40),
        ProviderMessage(role="user", content="recent question"),
    ]

    context = build_context(
        history=history,
        system_prompt="Be useful.",
        context_limit_tokens=40,
        reserved_output_tokens=10,
    )

    assert context.messages[0] == ProviderMessage(role="system", content="Be useful.")
    assert context.messages[-1].content == "recent question"
    assert context.estimated_input_tokens <= context.input_budget_tokens
    assert context.truncated_messages > 0


def test_oversized_latest_message_is_truncated_from_the_start() -> None:
    context = build_context(
        history=[ProviderMessage(role="user", content="a" * 800)],
        system_prompt="s",
        context_limit_tokens=20,
        reserved_output_tokens=5,
    )

    assert context.messages[-1].content == "a" * 56
    assert context.truncated_messages == 1
    assert context.estimated_input_tokens <= context.input_budget_tokens


def test_context_rejects_budgets_without_room_for_system_prompt() -> None:
    with pytest.raises(ValueError, match="System prompt"):
        build_context(
            history=[ProviderMessage(role="user", content="hello")],
            system_prompt="a" * 80,
            context_limit_tokens=20,
            reserved_output_tokens=5,
        )


def test_token_estimate_is_documented_character_approximation() -> None:
    assert estimate_tokens("abcdefgh") == 2
