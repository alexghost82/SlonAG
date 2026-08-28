"""Provider-neutral conversion helpers for OpenAI-compatible chat protocols."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass

from providers.contracts import ConversationMessage, ToolCall
from providers.errors import ProviderError


def message_payload(
    message: ConversationMessage, *, ollama: bool = False
) -> dict[str, object]:
    """Serialize one canonical message without losing native tool correlation."""
    if message.role == "tool":
        envelope: dict[str, object] = (
            {"error": message.error}
            if message.error is not None
            else {"result": message.result}
        )
        artifacts = getattr(message, "artifacts", ())
        if artifacts:
            envelope["artifacts"] = [
                asdict(item) if is_dataclass(item) else item for item in artifacts
            ]
        content = json.dumps(envelope)
        if ollama:
            return {"role": "tool", "content": content, "tool_name": message.name}
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": content,
        }

    item: dict[str, object] = {
        "role": message.role,
        "content": message.content,
    }
    calls = getattr(message, "tool_calls", ())
    if calls:
        item["tool_calls"] = [
            {
                "id": call.id,
                **({} if ollama else {"type": "function"}),
                "function": {
                    "name": call.name,
                    "arguments": (
                        dict(call.arguments)
                        if ollama
                        else json.dumps(call.arguments)
                    ),
                },
            }
            for call in calls
        ]
    return item


def messages_payload(
    messages: Sequence[ConversationMessage], *, ollama: bool = False
) -> list[dict[str, object]]:
    return [message_payload(message, ollama=ollama) for message in messages]


def parse_arguments(value: object, provider_id: str) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ProviderError(
            "provider returned invalid tool call arguments",
            provider_id=provider_id,
        )
    try:
        arguments = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "provider returned malformed tool call arguments",
            provider_id=provider_id,
        ) from exc
    if not isinstance(arguments, dict):
        raise ProviderError(
            "provider returned non-object tool call arguments",
            provider_id=provider_id,
        )
    return arguments


def parse_tool_calls(payload: object, provider_id: str) -> tuple[ToolCall, ...]:
    choice = _first_choice(payload)
    message = choice.get("message") if choice is not None else None
    raw_calls = message.get("tool_calls") if isinstance(message, dict) else None
    if raw_calls is None:
        return ()
    if not isinstance(raw_calls, list):
        raise ProviderError("provider returned invalid tool calls", provider_id=provider_id)
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        function = raw.get("function") if isinstance(raw, dict) else None
        if not isinstance(function, dict):
            raise ProviderError("provider returned invalid tool calls", provider_id=provider_id)
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ProviderError("provider returned unnamed tool call", provider_id=provider_id)
        call_id = raw.get("id")
        if not isinstance(call_id, str) or not call_id:
            call_id = f"{provider_id}-call-{index}"
        calls.append(
            ToolCall(
                id=call_id,
                name=name,
                arguments=parse_arguments(function.get("arguments", "{}"), provider_id),
            )
        )
    _reject_duplicate_ids(calls, provider_id)
    return tuple(calls)


class ToolCallStreamAssembler:
    """Bounded deterministic assembler for fragmented OpenAI tool calls."""

    def __init__(self, provider_id: str, *, max_calls: int = 128, max_bytes: int = 1_000_000) -> None:
        self.provider_id = provider_id
        self.max_calls = max_calls
        self.max_bytes = max_bytes
        self._pending: dict[int, dict[str, str]] = {}
        self._size = 0

    def add(self, payload: object) -> None:
        choice = _first_choice(payload)
        delta = choice.get("delta") if choice is not None else None
        values = delta.get("tool_calls") if isinstance(delta, dict) else None
        if values is None:
            return
        if not isinstance(values, list):
            self._invalid("invalid streamed tool calls")
        for value in values:
            if not isinstance(value, dict) or not isinstance(value.get("index"), int):
                self._invalid("invalid streamed tool call fragment")
            index = value["index"]
            if index < 0 or (index not in self._pending and len(self._pending) >= self.max_calls):
                self._invalid("too many streamed tool calls")
            call = self._pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
            call_id = value.get("id")
            if isinstance(call_id, str):
                call["id"] += call_id
                self._size += len(call_id)
            function = value.get("function")
            if isinstance(function, dict):
                name = function.get("name")
                arguments = function.get("arguments")
                if isinstance(name, str):
                    call["name"] += name
                    self._size += len(name)
                if isinstance(arguments, str):
                    call["arguments"] += arguments
                    self._size += len(arguments)
            if self._size > self.max_bytes:
                self._invalid("streamed tool calls exceed size limit")

    def finish(self) -> tuple[ToolCall, ...]:
        calls: list[ToolCall] = []
        for index, fragments in sorted(self._pending.items()):
            if not fragments["name"]:
                self._invalid("incomplete streamed tool call")
            calls.append(
                ToolCall(
                    id=fragments["id"] or f"{self.provider_id}-call-{index}",
                    name=fragments["name"],
                    arguments=parse_arguments(fragments["arguments"], self.provider_id),
                )
            )
        _reject_duplicate_ids(calls, self.provider_id)
        self._pending.clear()
        self._size = 0
        return tuple(calls)

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    def _invalid(self, message: str) -> None:
        raise ProviderError(message, provider_id=self.provider_id)


def finish_reason(payload: object) -> object:
    choice = _first_choice(payload)
    return choice.get("finish_reason") if choice is not None else None


def _first_choice(payload: object) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    return choices[0]


def _reject_duplicate_ids(calls: Sequence[ToolCall], provider_id: str) -> None:
    ids = [call.id for call in calls]
    if len(ids) != len(set(ids)):
        raise ProviderError("provider returned duplicate tool call ids", provider_id=provider_id)


from providers.openai.provider import OpenAIChatProvider


def create_openai_provider(
    api_key: str = "",
    *,
    base_url: str = "http://localhost:1234/v1",
) -> OpenAIChatProvider:
    """Create an OpenAI-compatible provider (LM Studio, Ollama, etc.)."""
    return OpenAIChatProvider(api_key=api_key, base_url=base_url)


__all__ = [
    "ToolCallStreamAssembler",
    "create_openai_provider",
    "finish_reason",
    "message_payload",
    "messages_payload",
    "parse_arguments",
    "parse_tool_calls",
]
