"""OpenRouter ``ChatProvider`` over the OpenAI-compatible HTTP API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from providers.capabilities import require_capability, require_provider_match
from providers.contracts import (
    ChatEvent,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
    ToolCall,
)
from providers.errors import ProviderAuthError, ProviderError
from providers.openrouter.catalog import parse_models_payload
from providers.openrouter.client import DEFAULT_API_URL, DEFAULT_TIMEOUT, OpenRouterClient, RequestFn
from providers.openrouter.errors import PROVIDER_ID
from providers.openai_compat import (
    ToolCallStreamAssembler,
    finish_reason,
    messages_payload,
    parse_tool_calls,
)


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
        require_provider_match(request.model, PROVIDER_ID)
        require_capability(request.model, request.role)
        data = self._http().post_json(self._api_url, _chat_payload(request))
        return ChatResponse(
            text=_message_text(data, PROVIDER_ID),
            provider_id=PROVIDER_ID,
            model_id=request.model.model_id,
            tool_calls=_tool_calls(data, PROVIDER_ID),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        require_provider_match(request.model, PROVIDER_ID)
        require_capability(request.model, request.role)
        payload = _chat_payload(request, stream=True)
        assembler = ToolCallStreamAssembler(PROVIDER_ID)
        for line in self._http().post_sse_lines(self._api_url, payload):
            event, data = _parse_sse_line_with_payload(line)
            if event is not None:
                yield event
            if data is not None:
                assembler.add(data)
                if finish_reason(data) == "tool_calls":
                    for call in assembler.finish():
                        yield ChatEvent(type="tool_call", tool_call=call)
        if assembler.pending:
            for call in assembler.finish():
                yield ChatEvent(type="tool_call", tool_call=call)
        yield ChatEvent(type="done")


def _normalize_key(api_key: str | None) -> str | None:
    if not isinstance(api_key, str):
        return None
    stripped = api_key.strip()
    return stripped or None


def _chat_payload(request: ChatRequest, *, stream: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model.model_id,
        "messages": messages_payload(request.messages),
    }
    if stream:
        payload["stream"] = True
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                },
            }
            for tool in request.tools
        ]
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    return payload


def _message_text(data: object, provider_id: str) -> str:
    if not isinstance(data, dict):
        raise ProviderError(
            "OpenRouter returned an invalid response (not an object)",
            provider_id=provider_id,
        )
    choices = data.get("choices")
    if choices is None or not isinstance(choices, list) or not choices:
        raise ProviderError(
            "OpenRouter returned no choices",
            provider_id=provider_id,
        )
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError(
            "OpenRouter returned an invalid response structure",
            provider_id=provider_id,
        )
    message = first.get("message")
    if not isinstance(message, dict):
        raise ProviderError(
            "OpenRouter response missing message field",
            provider_id=provider_id,
        )
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderError(
            "OpenRouter response content is not a string",
            provider_id=provider_id,
        )
    return content


def _tool_calls(data: object, provider_id: str) -> tuple[ToolCall, ...]:
    return parse_tool_calls(data, provider_id)


def _parse_sse_line(line: str) -> ChatEvent | None:
    event, _payload = _parse_sse_line_with_payload(line)
    return event


def _parse_sse_line_with_payload(line: str) -> tuple[ChatEvent | None, dict[str, Any] | None]:
    raw = line.strip()
    if raw.startswith("data:"):
        raw = raw[5:].strip()
    if not raw or raw == "[DONE]":
        return None, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    text = _delta_text(data)
    if not text:
        return None, data
    return ChatEvent(type="delta", text=text), data


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
