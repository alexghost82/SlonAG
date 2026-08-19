from __future__ import annotations

from providers.contracts import (
    ChatEvent,
    ChatMessage,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ProviderStatus,
    ToolCall,
    ToolDefinition,
)

from tests.unit.providers.mocks import MockChatProvider


def test_model_info_accepts_required_fields() -> None:
    info = ModelInfo(
        provider_id="gemini",
        model_id="gemini-flash",
        display_name="Gemini Flash",
        text=True,
        streaming=True,
        structured_output=True,
        tool_calling=True,
        vision=True,
        audio_input=True,
        audio_output=False,
        embeddings=False,
        context_length=1_000_000,
        local=False,
        source="Google",
        license="Proprietary",
        cost=0.15,
        ram_gb=None,
        vram_gb=8.0,
    )
    assert info.provider_id == "gemini"
    assert info.model_id == "gemini-flash"
    assert info.display_name == "Gemini Flash"
    assert info.text is True
    assert info.streaming is True
    assert info.structured_output is True
    assert info.tool_calling is True
    assert info.vision is True
    assert info.audio_input is True
    assert info.audio_output is False
    assert info.embeddings is False
    assert info.context_length == 1_000_000
    assert info.local is False
    assert info.source == "Google"
    assert info.license == "Proprietary"
    assert info.cost == 0.15
    assert info.ram_gb is None
    assert info.vram_gb == 8.0


def test_chat_event_shape_is_type_and_text() -> None:
    event = ChatEvent(type="delta", text="hello")
    assert event.type == "delta"
    assert event.text == "hello"
    done = ChatEvent(type="done")
    assert done.type == "done"
    assert done.text == ""


def test_tool_calling_contracts_are_provider_agnostic() -> None:
    tool = ToolDefinition(
        name="search_notes",
        description="Search saved notes",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    call = ToolCall(id="call-1", name="search_notes", arguments={"query": "Slon"})
    model = ModelInfo(
        provider_id="ollama",
        model_id="local-tools",
        display_name="Local Tools",
        text=True,
        tool_calling=True,
        local=True,
    )

    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="search"),),
        tools=(tool,),
        tool_choice="auto",
    )
    response = ChatResponse(
        text="",
        provider_id="ollama",
        model_id="local-tools",
        tool_calls=(call,),
    )
    event = ChatEvent(type="tool_call", tool_call=call)

    assert request.tools == (tool,)
    assert request.tool_choice == "auto"
    assert response.tool_calls == (call,)
    assert event.tool_call is call


def test_text_only_contract_defaults_remain_backward_compatible() -> None:
    model = ModelInfo(provider_id="mock", model_id="text", display_name="Text")
    request = ChatRequest(model, (ChatMessage(role="user", content="hello"),))
    response = ChatResponse("hello", "mock", "text")

    assert request.tools == ()
    assert request.tool_choice is None
    assert response.tool_calls == ()
    assert ChatEvent(type="done").tool_call is None


def test_mock_provider_satisfies_chat_protocol() -> None:
    provider = MockChatProvider("openai")
    assert isinstance(provider, ChatProvider)


def test_chat_request_is_provider_agnostic() -> None:
    model = ModelInfo(
        provider_id="openrouter",
        model_id="or-mock",
        display_name="OR mock",
        text=True,
    )
    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="ping"),),
        role="chat",
    )
    assert request.role == "chat"
    assert request.messages[0].content == "ping"
    response = ChatResponse(text="ok", provider_id="openrouter", model_id="or-mock")
    assert isinstance(response, ChatResponse)
    assert ProviderStatus(provider_id="openrouter", ok=True).ok is True
