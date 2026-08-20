"""Conversion between Wave 17 messages and durable transcript entries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypedDict

from providers.contracts import (
    AssistantMessage,
    AssistantToolCallMessage,
    ConversationMessage,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from sessions.contracts import TranscriptEntry, TranscriptKind, TranscriptState


class TranscriptFields(TypedDict, total=False):
    kind: TranscriptKind
    role: str
    text: str | None
    tool_call_id: str
    tool_name: str
    data: object
    artifacts: tuple[Mapping[str, object], ...]


def entry_fields(message: ConversationMessage) -> list[TranscriptFields]:
    if isinstance(message, AssistantToolCallMessage):
        return [
            {
                "kind": TranscriptKind.TOOL_CALL,
                "role": "assistant",
                "text": message.content if index == 0 else None,
                "tool_call_id": call.id,
                "tool_name": call.name,
                "data": dict(call.arguments),
            }
            for index, call in enumerate(message.tool_calls)
        ]
    if isinstance(message, ToolResultMessage):
        return [{
            "kind": TranscriptKind.TOOL_RESULT,
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "data": {"result": message.result, "error": message.error},
            "artifacts": tuple(_artifact(item) for item in message.artifacts),
        }]
    if isinstance(message, UserMessage):
        return [{"kind": TranscriptKind.TEXT, "role": "user", "text": message.content}]
    if isinstance(message, SystemMessage):
        return [{"kind": TranscriptKind.TEXT, "role": "system", "text": message.content}]
    if isinstance(message, AssistantMessage):
        return [{"kind": TranscriptKind.TEXT, "role": "assistant", "text": message.content}]
    raise TypeError(f"unsupported canonical message: {type(message).__name__}")


def messages_from_entries(entries: Iterable[TranscriptEntry]) -> tuple[ConversationMessage, ...]:
    result: list[ConversationMessage] = []
    pending_calls: list[ToolCall] = []
    pending_turn: str | None = None
    pending_text = ""

    def flush_calls() -> None:
        nonlocal pending_calls, pending_turn, pending_text
        if pending_calls:
            result.append(
                AssistantToolCallMessage(tuple(pending_calls), content=pending_text)
            )
        pending_calls = []
        pending_turn = None
        pending_text = ""

    for entry in entries:
        if entry.kind is TranscriptKind.TOOL_CALL:
            if pending_calls and entry.turn_id != pending_turn:
                flush_calls()
            pending_turn = entry.turn_id
            pending_text = pending_text or entry.text or ""
            arguments = entry.data if isinstance(entry.data, dict) else {}
            pending_calls.append(
                ToolCall(entry.tool_call_id or "", entry.tool_name or "", arguments)
            )
            continue
        flush_calls()
        if entry.kind is TranscriptKind.TEXT:
            if (
                entry.role == "assistant"
                and entry.state is not TranscriptState.COMPLETED
            ):
                continue
            if entry.role == "user":
                result.append(UserMessage(entry.text or ""))
            elif entry.role == "system":
                result.append(SystemMessage(entry.text or ""))
            elif entry.role == "assistant":
                result.append(AssistantMessage(entry.text or ""))
        elif entry.kind is TranscriptKind.TOOL_RESULT:
            payload = entry.data if isinstance(entry.data, dict) else {}
            result.append(ToolResultMessage(
                tool_call_id=entry.tool_call_id or "",
                tool_name=entry.tool_name or "",
                result=payload.get("result"), error=payload.get("error"),
                artifacts=entry.artifacts,
            ))
    flush_calls()
    protocol_safe: list[ConversationMessage] = []
    index = 0
    while index < len(result):
        message = result[index]
        protocol_safe.append(message)
        if isinstance(message, AssistantToolCallMessage):
            expected = {call.id: call.name for call in message.tool_calls}
            cursor = index + 1
            while cursor < len(result) and isinstance(result[cursor], ToolResultMessage):
                tool_result = result[cursor]
                assert isinstance(tool_result, ToolResultMessage)
                if tool_result.tool_call_id not in expected:
                    raise ValueError("unexpected or duplicate tool result in transcript")
                expected.pop(tool_result.tool_call_id)
                protocol_safe.append(tool_result)
                cursor += 1
            for call_id, name in expected.items():
                protocol_safe.append(ToolResultMessage(
                    tool_call_id=call_id,
                    tool_name=name,
                    error="Execution was interrupted; result is unknown and was not replayed.",
                ))
            index = cursor
            continue
        if isinstance(message, ToolResultMessage):
            raise ValueError("orphan tool result in transcript")
        index += 1
    return tuple(protocol_safe)


def _artifact(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    attributes = getattr(value, "__dict__", None)
    return dict(attributes) if isinstance(attributes, dict) else {"reference": str(value)}


__all__ = ["TranscriptFields", "entry_fields", "messages_from_entries"]
