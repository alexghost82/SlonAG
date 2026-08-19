from __future__ import annotations

import json

import pytest

from providers.contracts import (
    ChatMessage,
    ChatRequest,
    ModelInfo,
    ToolCall,
    ToolDefinition,
)
from providers.errors import CapabilityError
from providers.local import LlamaCppChatProvider, OpenAICompatibleChatProvider
from tests.unit.providers.local.fakes import FakeTransport


PROVIDERS = (OpenAICompatibleChatProvider, LlamaCppChatProvider)


def _request(provider_id: str, *, tool_calling: bool = True) -> ChatRequest:
    model = ModelInfo(
        provider_id=provider_id,
        model_id="explicit-tools-model",
        display_name="Explicit tools model",
        text=True,
        streaming=True,
        tool_calling=tool_calling,
        local=True,
    )
    return ChatRequest(
        model=model,
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


@pytest.mark.parametrize("factory", PROVIDERS)
async def test_chat_serializes_tools_and_parses_null_content_tool_call(factory) -> None:
    transport = FakeTransport(
        chat={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-weather",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"Paris"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )

    response = await factory(transport=transport).chat(_request(factory.provider_id))

    assert response.text == ""
    assert response.tool_calls == (
        ToolCall(
            id="call-weather",
            name="get_weather",
            arguments={"city": "Paris"},
        ),
    )
    body = transport.calls[0]["json_body"]
    assert isinstance(body, dict)
    assert body["tool_choice"] == "auto"
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


@pytest.mark.parametrize("factory", PROVIDERS)
async def test_stream_assembles_fragmented_tool_arguments(factory) -> None:
    transport = FakeTransport(
        stream_lines=(
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-weather",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": '{"city":',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '"Rome"}'},
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
            "data: [DONE]",
        )
    )

    events = [
        event
        async for event in factory(transport=transport).stream(
            _request(factory.provider_id)
        )
    ]

    assert [event.type for event in events] == ["tool_call", "done"]
    assert events[0].tool_call == ToolCall(
        id="call-weather", name="get_weather", arguments={"city": "Rome"}
    )
    assert transport.calls[0]["stream"] is True


@pytest.mark.parametrize("factory", PROVIDERS)
async def test_tools_require_explicit_model_capability_before_http(factory) -> None:
    transport = FakeTransport()
    with pytest.raises(CapabilityError, match="does not support tool calling"):
        await factory(transport=transport).chat(
            _request(factory.provider_id, tool_calling=False)
        )
    assert transport.calls == []


@pytest.mark.parametrize("factory", PROVIDERS)
async def test_catalog_does_not_optimistically_mark_models_tool_capable(
    factory,
) -> None:
    transport = FakeTransport(models={"data": [{"id": "unknown-model"}]})
    models = await factory(transport=transport).list_models()
    assert len(models) == 1
    assert models[0].tool_calling is False
