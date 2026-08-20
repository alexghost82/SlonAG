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
    ToolCall,
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
            tool_calls=_tool_calls(data),
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


def _messages_payload(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            value = message.error if message.error is not None else message.result
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": value if isinstance(value, str) else json.dumps(value),
                }
            )
            continue
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ]
        payload.append(item)
    return payload


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


def _tool_calls(data: object) -> tuple[ToolCall, ...]:
    if not isinstance(data, dict):
        return ()
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ()
    message = choices[0].get("message")
    raw_calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(raw_calls, list):
        return ()
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        function = raw.get("function") if isinstance(raw, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        encoded = function.get("arguments", "{}")
        try:
            arguments = json.loads(encoded) if isinstance(encoded, str) else encoded
        except json.JSONDecodeError:
            arguments = {"_malformed_arguments": encoded}
        if not isinstance(arguments, dict):
            arguments = {"_malformed_arguments": encoded}
        calls.append(ToolCall(str(raw.get("id") or f"call_{index}"), function["name"], arguments))
    return tuple(calls)


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
