"""Shared ChatProvider behavior for loopback local runtimes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from providers.capabilities import require_capability, require_provider_match
from providers.contracts import (
    ChatEvent,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
    ToolCall,
)
from providers.errors import (
    CapabilityError,
    ProviderAuthError,
    ProviderError,
    ProviderOfflineError,
)
from providers.local.capabilities import resolve_local_capabilities
from providers.local.endpoint import assert_endpoint_allowed, join_endpoint
from providers.local.http import StdlibTransport, Transport, TransportResponse
from providers.openai_compat import messages_payload

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_LLAMA_CPP_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT = 30.0
PROTOCOL_OPENAI = "openai"
PROTOCOL_OLLAMA = "ollama"


class BaseLocalChatProvider:
    """Loopback-first chat adapter. Failures never fall back to cloud."""

    provider_id: str = "local"
    default_base_url: str = DEFAULT_LOCAL_BASE_URL
    models_path: str = "/v1/models"
    chat_path: str = "/v1/chat/completions"
    protocol: str = PROTOCOL_OPENAI

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        allow_remote: bool = False,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.allow_remote = allow_remote
        self._transport = transport if transport is not None else StdlibTransport()
        assert_endpoint_allowed(
            self.base_url,
            allow_remote=self.allow_remote,
            provider_id=self.provider_id,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, "
            f"allow_remote={self.allow_remote})"
        )

    async def validate(self) -> ProviderStatus:
        assert_endpoint_allowed(
            self.base_url,
            allow_remote=self.allow_remote,
            provider_id=self.provider_id,
        )
        try:
            await self.list_models()
        except ProviderError as exc:
            return ProviderStatus(
                provider_id=self.provider_id,
                ok=False,
                message=str(exc),
            )
        return ProviderStatus(provider_id=self.provider_id, ok=True)

    async def list_models(self) -> list[ModelInfo]:
        response = self._request("GET", self.models_path)
        self._raise_http(response)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "local runtime returned an invalid models payload",
                provider_id=self.provider_id,
            ) from exc
        return self._parse_models(payload)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        require_provider_match(request.model, self.provider_id)
        require_capability(request.model, request.role)
        self._require_tool_capability(request)
        response = self._request(
            "POST",
            self.chat_path,
            json_body=self._chat_payload(request, stream=False),
        )
        self._raise_http(response)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "local runtime returned an invalid chat payload",
                provider_id=self.provider_id,
            ) from exc
        text, tool_calls = self._parse_chat_message(payload)
        return ChatResponse(
            text=text,
            provider_id=self.provider_id,
            model_id=request.model.model_id,
            tool_calls=tool_calls,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        require_provider_match(request.model, self.provider_id)
        require_capability(request.model, request.role)
        self._require_tool_capability(request)
        response = self._request(
            "POST",
            self.chat_path,
            json_body=self._chat_payload(request, stream=True),
            stream=True,
        )
        self._raise_http(response)
        if self.protocol == PROTOCOL_OLLAMA:
            async for event in self._iter_ollama_stream(response):
                yield event
        else:
            async for event in self._iter_openai_stream(response):
                yield event
        yield ChatEvent(type="done")

    def _chat_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, object]:
        messages = messages_payload(
            request.messages, ollama=self.protocol == PROTOCOL_OLLAMA
        )
        payload: dict[str, object] = {
            "model": request.model.model_id,
            "messages": messages,
            "stream": stream,
        }
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
            # Ollama's native /api/chat contract supports tools, but does not
            # define OpenAI's tool_choice field.
            if request.tool_choice is not None and self.protocol != PROTOCOL_OLLAMA:
                payload["tool_choice"] = request.tool_choice
        return payload

    def _require_tool_capability(self, request: ChatRequest) -> None:
        if request.tools and not request.model.tool_calling:
            raise CapabilityError(
                f"model {request.model.model_id!r} does not support tool calling",
                provider_id=request.model.provider_id,
                role=request.role,
                model_id=request.model.model_id,
            )

    def _parse_models(self, payload: object) -> list[ModelInfo]:
        if not isinstance(payload, dict):
            raise ProviderError(
                "local runtime returned an invalid models payload",
                provider_id=self.provider_id,
            )
        if self.protocol == PROTOCOL_OLLAMA:
            items = payload.get("models")
        else:
            items = payload.get("data")
        if not isinstance(items, list):
            return []
        models: list[ModelInfo] = []
        for item in items:
            model_id = _catalog_model_id(item, ollama=self.protocol == PROTOCOL_OLLAMA)
            if model_id is None:
                continue
            models.append(self._model_info(model_id, item))
        return models

    def _parse_chat_message(self, payload: object) -> tuple[str, tuple[ToolCall, ...]]:
        if not isinstance(payload, dict):
            raise ProviderError(
                "local runtime returned an invalid chat payload",
                provider_id=self.provider_id,
            )
        if self.protocol == PROTOCOL_OLLAMA:
            message = payload.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                tool_calls = _ollama_tool_calls(
                    message.get("tool_calls"), self.provider_id
                )
                if isinstance(content, str) and (content or tool_calls):
                    return content, tool_calls
            raise ProviderError(
                "ollama chat payload is missing message content",
                provider_id=self.provider_id,
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError(
                "chat payload is missing choices",
                provider_id=self.provider_id,
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise ProviderError(
                "chat payload is missing choices",
                provider_id=self.provider_id,
            )
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            tool_calls = _openai_tool_calls(message.get("tool_calls"), self.provider_id)
            if isinstance(content, str):
                return content, tool_calls
            if content is None and tool_calls:
                return "", tool_calls
        raise ProviderError(
            "chat payload is missing message content",
            provider_id=self.provider_id,
        )

    def _parse_chat_text(self, payload: object) -> str:
        """Compatibility helper retained for text-only callers."""
        return self._parse_chat_message(payload)[0]

    async def _iter_openai_stream(
        self, response: TransportResponse
    ) -> AsyncIterator[ChatEvent]:
        pending_calls: dict[int, dict[str, str]] = {}

        def completed_calls() -> tuple[ToolCall, ...]:
            calls = _openai_stream_tool_calls(pending_calls, self.provider_id)
            pending_calls.clear()
            return calls

        for line in response.iter_lines():
            stripped = line.strip()
            if not stripped or stripped.startswith(":"):
                continue
            if not stripped.startswith("data:"):
                continue
            data = stripped[5:].strip()
            if data == "[DONE]":
                for tool_call in completed_calls():
                    yield ChatEvent(type="tool_call", tool_call=tool_call)
                return
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    "local runtime returned an invalid stream chunk",
                    provider_id=self.provider_id,
                ) from exc
            text = _openai_delta_text(payload)
            if text:
                yield ChatEvent(type="delta", text=text)
            _accumulate_openai_tool_deltas(payload, pending_calls, self.provider_id)
            if _openai_finish_reason(payload) == "tool_calls":
                for tool_call in completed_calls():
                    yield ChatEvent(type="tool_call", tool_call=tool_call)
        for tool_call in completed_calls():
            yield ChatEvent(type="tool_call", tool_call=tool_call)

    async def _iter_ollama_stream(
        self, response: TransportResponse
    ) -> AsyncIterator[ChatEvent]:
        raw_tool_calls: list[object] = []
        for line in response.iter_lines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    "local runtime returned an invalid stream chunk",
                    provider_id=self.provider_id,
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderError(
                    "local runtime returned an invalid stream chunk",
                    provider_id=self.provider_id,
                )
            message = payload.get("message")
            if isinstance(message, dict):
                text = message.get("content")
                if isinstance(text, str) and text:
                    yield ChatEvent(type="delta", text=text)
                calls = message.get("tool_calls")
                if isinstance(calls, list):
                    raw_tool_calls.extend(calls)
            if payload.get("done") is True:
                for tool_call in _ollama_tool_calls(
                    raw_tool_calls, self.provider_id
                ):
                    yield ChatEvent(type="tool_call", tool_call=tool_call)
                return
        for tool_call in _ollama_tool_calls(raw_tool_calls, self.provider_id):
            yield ChatEvent(type="tool_call", tool_call=tool_call)

    def _model_info(self, model_id: str, runtime_metadata: object) -> ModelInfo:
        metadata = runtime_metadata if isinstance(runtime_metadata, dict) else {}
        source = metadata.get("owned_by")
        resolved_source = (
            source if isinstance(source, str) and source else self.provider_id
        )
        capabilities = resolve_local_capabilities(
            self.provider_id,
            model_id,
            metadata,
        )
        return ModelInfo(
            provider_id=self.provider_id,
            model_id=model_id,
            display_name=model_id,
            text=capabilities.text,
            streaming=capabilities.streaming,
            structured_output=capabilities.structured_output,
            tool_calling=capabilities.tool_calling,
            vision=capabilities.vision,
            context_length=capabilities.context_length,
            local=True,
            source=resolved_source,
            license="",
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        stream: bool = False,
    ) -> TransportResponse:
        assert_endpoint_allowed(
            self.base_url,
            allow_remote=self.allow_remote,
            provider_id=self.provider_id,
        )
        url = join_endpoint(self.base_url, path)
        try:
            return self._transport.request(
                method,
                url,
                headers=self._headers(),
                json_body=json_body,
                stream=stream,
                timeout=DEFAULT_TIMEOUT,
            )
        except ProviderError:
            raise
        except (OSError, TimeoutError) as exc:
            raise ProviderOfflineError(
                "local runtime is unreachable",
                provider_id=self.provider_id,
            ) from exc

    def _raise_http(self, response: TransportResponse) -> None:
        if response.status_code in {401, 403}:
            raise ProviderAuthError(
                f"local runtime rejected credentials (HTTP {response.status_code})",
                provider_id=self.provider_id,
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"local runtime returned HTTP {response.status_code}",
                provider_id=self.provider_id,
            )


def _catalog_model_id(item: object, *, ollama: bool) -> str | None:
    if not isinstance(item, dict):
        return None
    if ollama:
        for key in ("name", "model"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        return None
    value = item.get("id")
    if isinstance(value, str) and value:
        return value
    return None


def _openai_delta_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    text = delta.get("content")
    return text if isinstance(text, str) else ""


def _openai_first_choice(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    return choices[0]


def _openai_finish_reason(payload: object) -> object:
    choice = _openai_first_choice(payload)
    return choice.get("finish_reason") if choice is not None else None


def _openai_tool_calls(value: object, provider_id: str) -> tuple[ToolCall, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProviderError(
            "chat payload has invalid tool calls", provider_id=provider_id
        )
    calls: list[ToolCall] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
            raise ProviderError(
                "chat payload has invalid tool calls", provider_id=provider_id
            )
        function = item["function"]
        name = function.get("name")
        arguments = _openai_arguments(function.get("arguments"), provider_id)
        if not isinstance(name, str) or not name:
            raise ProviderError(
                "chat payload has invalid tool calls", provider_id=provider_id
            )
        call_id = item.get("id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"openai-call-{index}"
        calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    _reject_duplicate_tool_ids(calls, provider_id)
    return tuple(calls)


def _openai_arguments(value: object, provider_id: str) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ProviderError(
            "chat payload has invalid tool call arguments", provider_id=provider_id
        )
    try:
        arguments = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "chat payload has invalid tool call arguments", provider_id=provider_id
        ) from exc
    if not isinstance(arguments, dict):
        raise ProviderError(
            "chat payload has invalid tool call arguments", provider_id=provider_id
        )
    return arguments


def _accumulate_openai_tool_deltas(
    payload: object,
    pending: dict[int, dict[str, str]],
    provider_id: str,
) -> None:
    choice = _openai_first_choice(payload)
    delta = choice.get("delta") if choice is not None else None
    if not isinstance(delta, dict) or delta.get("tool_calls") is None:
        return
    values = delta["tool_calls"]
    if not isinstance(values, list):
        raise ProviderError(
            "local runtime returned invalid streamed tool calls",
            provider_id=provider_id,
        )
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("index"), int):
            raise ProviderError(
                "local runtime returned invalid streamed tool calls",
                provider_id=provider_id,
            )
        index = value["index"]
        call = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
        call_id = value.get("id")
        if isinstance(call_id, str):
            call["id"] += call_id
        function = value.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            arguments = function.get("arguments")
            if isinstance(name, str):
                call["name"] += name
            if isinstance(arguments, str):
                call["arguments"] += arguments


def _openai_stream_tool_calls(
    pending: dict[int, dict[str, str]], provider_id: str
) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for index, fragments in sorted(pending.items()):
        name = fragments["name"]
        if not name:
            raise ProviderError(
                "local runtime returned incomplete streamed tool call",
                provider_id=provider_id,
            )
        calls.append(
            ToolCall(
                id=fragments["id"] or f"openai-call-{index}",
                name=name,
                arguments=_openai_arguments(fragments["arguments"], provider_id),
            )
        )
    _reject_duplicate_tool_ids(calls, provider_id)
    return tuple(calls)


def _ollama_tool_calls(value: object, provider_id: str) -> tuple[ToolCall, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProviderError(
            "ollama chat payload has invalid tool calls", provider_id=provider_id
        )
    calls: list[ToolCall] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ProviderError(
                "ollama chat payload has invalid tool calls", provider_id=provider_id
            )
        function = item.get("function")
        if not isinstance(function, dict):
            raise ProviderError(
                "ollama chat payload has invalid tool calls", provider_id=provider_id
            )
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name or not isinstance(arguments, dict):
            raise ProviderError(
                "ollama chat payload has invalid tool calls", provider_id=provider_id
            )
        call_id = item.get("id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"ollama-call-{index}"
        calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    _reject_duplicate_tool_ids(calls, provider_id)
    return tuple(calls)


def _reject_duplicate_tool_ids(calls: list[ToolCall], provider_id: str) -> None:
    ids = [call.id for call in calls]
    if len(ids) != len(set(ids)):
        raise ProviderError(
            "local runtime returned duplicate tool call ids",
            provider_id=provider_id,
        )
