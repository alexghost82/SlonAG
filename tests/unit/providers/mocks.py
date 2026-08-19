"""In-memory ChatProvider mocks. No network I/O and no secret access."""

from __future__ import annotations

from collections.abc import AsyncIterator

from providers.capabilities import require_capability
from providers.contracts import (
    ChatEvent,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
)

REPLY_PREFIX = "mock-reply:"


def mock_model(
    provider_id: str,
    *,
    text: bool = True,
    streaming: bool = True,
    local: bool | None = None,
    **overrides: object,
) -> ModelInfo:
    """Build a catalog entry for a mock provider."""
    is_local = provider_id == "local" if local is None else local
    fields: dict[str, object] = {
        "provider_id": provider_id,
        "model_id": f"{provider_id}-mock",
        "display_name": f"{provider_id} mock",
        "text": text,
        "streaming": streaming,
        "structured_output": False,
        "tool_calling": False,
        "vision": False,
        "audio_input": False,
        "audio_output": False,
        "embeddings": False,
        "context_length": 8192,
        "local": is_local,
        "source": "test",
        "license": "test",
    }
    fields.update(overrides)
    return ModelInfo(**fields)  # type: ignore[arg-type]


def _user_text(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return ""


class MockChatProvider:
    """ChatProvider stand-in used by unit tests for every provider id."""

    def __init__(
        self,
        provider_id: str,
        *,
        models: list[ModelInfo] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._models = list(models) if models is not None else [mock_model(provider_id)]
        self.chat_calls = 0
        self.stream_calls = 0

    async def list_models(self) -> list[ModelInfo]:
        return list(self._models)

    async def validate(self) -> ProviderStatus:
        return ProviderStatus(provider_id=self.provider_id, ok=True)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        require_capability(request.model, request.role)
        self.chat_calls += 1
        return ChatResponse(
            text=f"{REPLY_PREFIX} {_user_text(request)}",
            provider_id=self.provider_id,
            model_id=request.model.model_id,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        require_capability(request.model, request.role)
        self.stream_calls += 1
        full = f"{REPLY_PREFIX} {_user_text(request)}"
        mid = max(1, len(full) // 2)
        yield ChatEvent(type="delta", text=full[:mid])
        yield ChatEvent(type="delta", text=full[mid:])
        yield ChatEvent(type="done")
