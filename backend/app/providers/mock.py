from collections.abc import Iterator

from app.providers.base import AIProvider, GenerationRequest


class MockProvider(AIProvider):
    name = "mock"

    def __init__(self, model: str = "deterministic-mock") -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, request: GenerationRequest) -> str:
        return "".join(self.stream(request))

    def stream(self, request: GenerationRequest) -> Iterator[str]:
        latest_user_message = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "",
        )
        response = f"Mock response: {latest_user_message}"
        for index in range(0, len(response), 12):
            yield response[index : index + 12]
