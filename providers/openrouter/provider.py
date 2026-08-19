"""OpenRouter ``ChatProvider`` over the OpenAI-compatible HTTP API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from providers.capabilities import require_capability
from providers.contracts import (
    ChatEvent,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
)
from providers.errors import ProviderAuthError
from providers.openrouter.catalog import parse_models_payload
from providers.openrouter.client import DEFAULT_API_URL, DEFAULT_TIMEOUT, OpenRouterClient, RequestFn
from providers.openrouter.errors import PROVIDER_ID


class OpenRouterChatProvider:
    """Single-model OpenRouter chat. Constructor ``api_key`` only."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_url: str = DEFAULT_API_URL,
        request: RequestFn | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.provider_id = PROVIDER_ID
        self._api_key = _normalize_key(api_key)
        self._api_url = api_url
        self._request = request
        self._timeout = timeout
        self._client: OpenRouterClient | None = None

    def _http(self) -> OpenRouterClient:
        if self._api_key is None:
            raise ProviderAuthError("missing api_key", provider_id=PROVIDER_ID)
        if self._client is None:
            self._client = OpenRouterClient(
                self._api_key,
                api_url=self._api_url,
                request=self._request,
                timeout=self._timeout,
            )
        return self._client

    async def validate(self) -> ProviderStatus:
        if self._api_key is None:
            return ProviderStatus(
                provider_id=PROVIDER_ID,
                ok=False,
                message="missing api_key",
            )
        return ProviderStatus(provider_id=PROVIDER_ID, ok=True)

    async def list_models(self) -> list[ModelInfo]:
        client = self._http()
        return parse_models_payload(client.get_json(client.models_url))

    async def chat(self, request: ChatRequest) -> ChatResponse:
        require_capability(request.model, request.role)
        data = self._http().post_json(self._api_url, _chat_payload(request))
        return ChatResponse(
            text=_message_text(data),
            provider_id=PROVIDER_ID,
            model_id=request.model.model_id,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        require_capability(request.model, request.role)
        payload = _chat_payload(request, stream=True)
        for line in self._http().post_sse_lines(self._api_url, payload):
            event = _parse_sse_line(line)
            if event is not None:
                yield event
        yield ChatEvent(type="done")


def _normalize_key(api_key: str | None) -> str | None:
    if not isinstance(api_key, str):
        return None
    stripped = api_key.strip()
    return stripped or None


def _chat_payload(request: ChatRequest, *, stream: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model.model_id,
        "messages": _messages_payload(request.messages),
    }
    if stream:
        payload["stream"] = True
    return payload


def _messages_payload(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _message_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message") or {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _parse_sse_line(line: str) -> ChatEvent | None:
    raw = line.strip()
    if raw.startswith("data:"):
        raw = raw[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    text = _delta_text(data)
    if not text:
        return None
    return ChatEvent(type="delta", text=text)


def _delta_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta") or {}
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    message = first.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""
