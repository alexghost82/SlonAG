from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent.runtime import AgentLoop
from providers.contracts import (
    AssistantToolCallMessage,
    ChatEvent,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from providers.errors import CapabilityError, ProviderError
from providers.gemini.provider import _contents_and_config
from providers.local import OpenAICompatibleChatProvider
from providers.openai.provider import OpenAIChatProvider
from providers.openai_compat import ToolCallStreamAssembler, message_payload
from providers.router import Router
from tests.unit.providers.local.fakes import FakeTransport


def _model(provider_id: str, *, tools: bool = True) -> ModelInfo:
    return ModelInfo(
        provider_id=provider_id,
        model_id=f"{provider_id}-model",
        display_name=provider_id,
        text=True,
        streaming=True,
        tool_calling=tools,
        local=provider_id in {"local", "ollama", "llama_cpp"},
    )


def _conversation() -> tuple[object, ...]:
    calls = (
        ToolCall("call-a", "weather_report", {"city": "Haifa"}),
        ToolCall("call-b", "weather_report", {"city": "Eilat"}),
    )
    return (
        SystemMessage("Be concise"),
        UserMessage("Weather"),
        AssistantToolCallMessage(calls, content="Checking"),
        ToolResultMessage(
            "call-a",
            "weather_report",
            result={"temp": 25},
            artifacts=({"kind": "report", "uri": "memory://weather"},),
        ),
        ToolResultMessage("call-b", "weather_report", error="offline"),
    )


def test_openai_native_messages_keep_calls_results_errors_and_artifacts() -> None:
    payloads = [message_payload(message) for message in _conversation()]
    assert [call["id"] for call in payloads[2]["tool_calls"]] == ["call-a", "call-b"]
    success = json.loads(payloads[3]["content"])
    assert success == {
        "result": {"temp": 25},
        "artifacts": [{"kind": "report", "uri": "memory://weather"}],
    }
    assert payloads[3]["tool_call_id"] == "call-a"
    assert json.loads(payloads[4]["content"]) == {"error": "offline"}


def test_gemini_native_messages_keep_calls_results_errors_and_artifacts() -> None:
    contents, config = _contents_and_config(_conversation())
    assert config == {"system_instruction": "Be concise"}
    calls = contents[1]["parts"][1:]
    assert [part["function_call"]["id"] for part in calls] == ["call-a", "call-b"]
    response = contents[2]["parts"][0]["function_response"]
    assert response["id"] == "call-a"
    assert response["response"]["artifacts"][0]["kind"] == "report"
    assert contents[3]["parts"][0]["function_response"]["response"] == {
        "error": "offline"
    }


def test_stream_assembler_correlates_fragmented_multiple_calls_in_order() -> None:
    assembler = ToolCallStreamAssembler("openai")
    assembler.add({"choices": [{"delta": {"tool_calls": [
        {"index": 1, "id": "b", "function": {"name": "second", "arguments": "{"}},
        {"index": 0, "id": "a", "function": {"name": "first", "arguments": "{"}},
    ]}}]})
    assembler.add({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": "}"}},
        {"index": 1, "function": {"arguments": "}"}},
    ]}}]})
    assert assembler.finish() == (
        ToolCall("a", "first", {}),
        ToolCall("b", "second", {}),
    )


def test_stream_assembler_is_bounded_and_rejects_malformed_arguments() -> None:
    assembler = ToolCallStreamAssembler("openai", max_calls=1, max_bytes=20)
    assembler.add({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "a", "function": {"name": "first", "arguments": "{"}},
    ]}}]})
    with pytest.raises(ProviderError, match="malformed"):
        assembler.finish()


@pytest.mark.asyncio
async def test_local_native_continuation_reaches_second_request() -> None:
    transport = FakeTransport(chat={"choices": [{"message": {"content": "done"}}]})
    provider = OpenAICompatibleChatProvider(transport=transport)
    request = ChatRequest(model=_model("local"), messages=_conversation())
    response = await provider.chat(request)
    assert response.text == "done"
    messages = transport.calls[0]["json_body"]["messages"]
    assert messages[2]["tool_calls"][0]["id"] == "call-a"
    assert messages[3]["tool_call_id"] == "call-a"
    assert json.loads(messages[4]["content"]) == {"error": "offline"}


@pytest.mark.asyncio
async def test_adapter_rejects_provider_mismatch_before_io() -> None:
    provider = OpenAIChatProvider(api_key=None)
    request = ChatRequest(model=_model("gemini"), messages=(UserMessage("hi"),))
    with pytest.raises(CapabilityError, match="does not match"):
        await provider.chat(request)


@pytest.mark.asyncio
async def test_router_rejects_mismatched_response_metadata() -> None:
    provider = MagicMock()

    async def chat(_request: ChatRequest) -> ChatResponse:
        return ChatResponse("bad", "other", "other-model")

    provider.chat.side_effect = chat
    router = Router(provider_id="openai", providers={"openai": provider})
    with pytest.raises(ProviderError, match="does not match"):
        await router.chat(ChatRequest(_model("openai"), (UserMessage("hi"),)))


@pytest.mark.asyncio
async def test_agent_loop_rejects_duplicate_ids_without_executing_tool() -> None:
    provider = MagicMock()

    async def chat(_request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            "",
            "test",
            "test-model",
            (ToolCall("dup", "one", {}), ToolCall("dup", "two", {})),
        )

    provider.chat.side_effect = chat
    executor = MagicMock()
    result = await AgentLoop(
        model=ModelInfo("test", "test-model", "test", text=True, tool_calling=True),
        provider=provider,
        tool_executor=executor,
    ).run("run")
    assert result.ok is False
    assert "duplicate tool_call_id" in result.reason.lower()
    executor.execute.assert_not_called()


def test_chat_event_rejects_incomplete_tool_call() -> None:
    with pytest.raises(ValueError, match="requires"):
        ChatEvent(type="tool_call")
