from dataclasses import dataclass

from app.providers.base import ProviderMessage


@dataclass(frozen=True)
class ContextWindow:
    messages: tuple[ProviderMessage, ...]
    estimated_input_tokens: int
    input_budget_tokens: int
    truncated_messages: int
    strategy: str


def estimate_tokens(text: str) -> int:
    """Conservative, model-agnostic approximation: one token per four characters."""
    return (len(text) + 3) // 4


def build_context(
    *,
    history: list[ProviderMessage],
    system_prompt: str,
    context_limit_tokens: int,
    reserved_output_tokens: int,
) -> ContextWindow:
    if context_limit_tokens < 1 or reserved_output_tokens < 0:
        raise ValueError("Token budgets must be positive.")
    if reserved_output_tokens >= context_limit_tokens:
        raise ValueError("Reserved output capacity must be below the context limit.")

    input_budget = context_limit_tokens - reserved_output_tokens
    system_message = ProviderMessage(role="system", content=system_prompt)
    system_tokens = estimate_tokens(system_prompt)
    if system_tokens >= input_budget:
        raise ValueError("System prompt leaves no room for conversation context.")

    remaining = input_budget - system_tokens
    selected_reversed: list[ProviderMessage] = []
    truncated_count = 0
    for reverse_index, message in enumerate(reversed(history)):
        message_tokens = estimate_tokens(message.content)
        if message_tokens <= remaining:
            selected_reversed.append(message)
            remaining -= message_tokens
            continue
        if not selected_reversed and remaining > 0:
            kept_chars = remaining * 4
            selected_reversed.append(
                ProviderMessage(
                    role=message.role,
                    content=message.content[-kept_chars:],
                )
            )
        truncated_count += len(history) - reverse_index
        break

    selected = [system_message, *reversed(selected_reversed)]
    estimated_input = sum(estimate_tokens(message.content) for message in selected)
    return ContextWindow(
        messages=tuple(selected),
        estimated_input_tokens=estimated_input,
        input_budget_tokens=input_budget,
        truncated_messages=truncated_count,
        strategy="recent_messages_with_safe_tail_truncation",
    )
