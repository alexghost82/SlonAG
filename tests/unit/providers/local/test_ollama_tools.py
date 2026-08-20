from __future__ import annotations

import pytest

from providers.contracts import (
    AssistantToolCallMessage,
    ChatMessage,
    ChatRequest,
    ModelInfo,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
)
from providers.errors import CapabilityError, ProviderError
from providers.local import OllamaChatProvider
from tests.unit.providers.local.fakes import FakeTransport


def _model(*, tool_calling: bool = True) -> ModelInfo:
    return ModelInfo(
        provider_id="ollama",
        model_id="tools-model",
        display_name="tools-model",
        text=True,
        streaming=True,
        tool_calling=tool_calling,
        local=True,
    )


def _request(*, tool_calling: bool = True) -> ChatRequest:
    return ChatRequest(
        model=_model(tool_calling=tool_calling),
        messages=(ChatMessage(role="user", content="Weather?"),),
        tools=(
            ToolDefinition(
                name="get_weather",
                description="Get current weather",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            ),
        ),
        tool_choice="auto",
    )


async def test_chat_serializes_tools_and_parses_tool_calls() -> None:
    transport = FakeTransport(
        chat={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_weather",
                            "arguments": {"city": "Paris"},
                        }
                    }
                ],
            },
            "done": True,
        }
    )
    response = await OllamaChatProvider(transport=transport).chat(_request())
    assert response.text == ""
    assert response.tool_calls == (
        ToolCall(
            id="ollama-call-0",
            name="get_weather",
            arguments={"city": "Paris"},
        ),
    )
    body = transport.calls[0]["json_body"]
    assert isinstance(body, dict)
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    assert "tool_choice" not in body
    assert body["stream"] is False


async def test_tool_stream_uses_non_stream_request_and_emits_canonical_call() -> None:
    transport = FakeTransport(
        stream_lines=(
            '{"message":{"content":"Calling weather"},"done":false}',
            '{"message":{"content":"","tool_calls":[{"id":"call-weather",'
            '"function":{"name":"get_weather","arguments":{"city":"Rome"}}}]},'
            '"done":true}',
        )
    )
    events = [
        event
        async for event in OllamaChatProvider(transport=transport).stream(_request())
    ]
    assert [event.type for event in events] == ["delta", "tool_call", "done"]
    assert events[1].tool_call == ToolCall(
        id="call-weather", name="get_weather", arguments={"city": "Rome"}
    )
    assert len(transport.calls) == 1
    assert transport.calls[0]["stream"] is True
    assert transport.calls[0]["json_body"]["stream"] is True


async def test_unknown_tool_capability_is_rejected_before_http() -> None:
    transport = FakeTransport()
    with pytest.raises(CapabilityError, match="does not support tool calling"):
        await OllamaChatProvider(transport=transport).chat(_request(tool_calling=False))
    assert transport.calls == []


async def test_text_only_payload_is_unchanged() -> None:
    transport = FakeTransport(
        chat={"message": {"role": "assistant", "content": "pong"}, "done": True}
    )
    request = ChatRequest(
        model=_model(tool_calling=False),
        messages=(ChatMessage(role="user", content="ping"),),
    )
    response = await OllamaChatProvider(transport=transport).chat(request)
    assert response.text == "pong"
    assert response.tool_calls == ()
    body = transport.calls[0]["json_body"]
    assert isinstance(body, dict)
    assert "tools" not in body
    assert "tool_choice" not in body


async def test_native_continuation_uses_ollama_tool_name_contract() -> None:
    call = ToolCall("internal-call", "get_weather", {"city": "Paris"})
    base = _request()
    request = ChatRequest(
        model=base.model,
        messages=(
            ChatMessage(role="user", content="Weather?"),
            AssistantToolCallMessage((call,)),
            ToolResultMessage(
                "internal-call", "get_weather", result={"temperature": 22}
            ),
        ),
        tools=base.tools,
    )
    transport = FakeTransport(
        chat={"message": {"role": "assistant", "content": "22 C"}}
    )
    await OllamaChatProvider(transport=transport).chat(request)
    messages = transport.calls[0]["json_body"]["messages"]
    assert messages[1]["tool_calls"][0]["id"] == "internal-call"
    assert messages[2]["tool_name"] == "get_weather"
    assert "tool_call_id" not in messages[2]  # Ollama native API correlates by name/order.


async def test_duplicate_native_ollama_ids_are_rejected() -> None:
    duplicate = {
        "id": "same",
        "function": {"name": "get_weather", "arguments": {"city": "Paris"}},
    }
    transport = FakeTransport(
        chat={"message": {"role": "assistant", "content": "", "tool_calls": [duplicate, duplicate]}}
    )
    with pytest.raises(ProviderError, match="duplicate"):
        await OllamaChatProvider(transport=transport).chat(_request())
