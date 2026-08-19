"""OpenAI ``ChatProvider`` implemented with constructor-only credentials.

``list_models`` marks capabilities conservatively: a chat model is text and
streaming only unless the id is clearly embeddings, STT, or TTS. Vision,
tools, and structured output are never inferred from a model name.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

from providers.capabilities import require_capability
from providers.contracts import (
    ChatEvent,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
)
from providers.errors import ProviderAuthError
from providers.openai.client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    OpenAIHttpClient,
    extract_delta_text,
    extract_message_text,
)
from providers.registry import register

PROVIDER_ID = "openai"

_EMBEDDING_MARKERS = ("embed", "embedding")
_STT_MARKERS = ("whisper", "transcribe")
_TTS_MARKERS = ("tts",)
_IMAGE_MARKERS = ("dall-e", "dall·e", "gpt-image")


class OpenAIChatProvider:
    """Cloud OpenAI chat adapter. One request uses exactly one model id."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: OpenAIHttpClient | None = None,
    ) -> None:
        self.provider_id = PROVIDER_ID
        self.api_key = _normalize_key(api_key)
        self.base_url = base_url
        self.timeout = timeout
        self._client = client

    async def list_models(self) -> list[ModelInfo]:
        payload = self._http().list_models()
        raw = payload.get("data")
        if not isinstance(raw, list):
            return []
        models: list[ModelInfo] = []
        for item in raw:
            if isinstance(item, dict) and item.get("id"):
                models.append(_model_info(item))
        return models

    async def validate(self) -> ProviderStatus:
        if self.api_key is None:
            return ProviderStatus(
                provider_id=PROVIDER_ID,
                ok=False,
                message="openai api key is missing",
            )
        return ProviderStatus(provider_id=PROVIDER_ID, ok=True)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        require_capability(request.model, request.role)
        payload = self._http().chat_completion(self._chat_body(request, stream=False))
        return ChatResponse(
            text=extract_message_text(payload),
            provider_id=PROVIDER_ID,
            model_id=request.model.model_id,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        require_capability(request.model, request.role)
        for event in self._http().stream_chat_completion(
            self._chat_body(request, stream=True)
        ):
            text = extract_delta_text(event)
            if text:
                yield ChatEvent(type="delta", text=text)
        yield ChatEvent(type="done")

    def _http(self) -> OpenAIHttpClient:
        if self.api_key is None:
            raise ProviderAuthError(
                "openai api key is missing",
                provider_id=PROVIDER_ID,
            )
        if self._client is None:
            self._client = OpenAIHttpClient(
                self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def _chat_body(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        return {
            "model": request.model.model_id,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "stream": stream,
        }


def conservative_capabilities(model_id: str) -> dict[str, bool]:
    """Capability flags that never assume vision, tools, or audio on chat models."""
    lowered = model_id.lower()
    flags = {
        "text": False,
        "streaming": False,
        "structured_output": False,
        "tool_calling": False,
        "vision": False,
        "audio_input": False,
        "audio_output": False,
        "embeddings": False,
    }
    if _contains_any(lowered, _EMBEDDING_MARKERS):
        flags["embeddings"] = True
        return flags
    if _contains_any(lowered, _STT_MARKERS):
        flags["audio_input"] = True
        return flags
    if _contains_any(lowered, _TTS_MARKERS):
        flags["audio_output"] = True
        return flags
    if _contains_any(lowered, _IMAGE_MARKERS):
        return flags
    flags["text"] = True
    flags["streaming"] = True
    return flags


def _model_info(item: Mapping[str, Any]) -> ModelInfo:
    model_id = str(item["id"])
    return ModelInfo(
        provider_id=PROVIDER_ID,
        model_id=model_id,
        display_name=model_id,
        context_length=0,
        local=False,
        source="OpenAI",
        license="Proprietary",
        **conservative_capabilities(model_id),
    )


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _normalize_key(api_key: str | None) -> str | None:
    if not isinstance(api_key, str):
        return None
    stripped = api_key.strip()
    return stripped or None


register("openai", OpenAIChatProvider)
