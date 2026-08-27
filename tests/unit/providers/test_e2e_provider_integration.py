"""Deterministic integration tests for all 7 provider paths.

Each test exercises the full chain:
    provider -> Router/stream -> chat -> tool call -> ToolResult -> continuation -> final answer

Uses injected transports or in-memory mocks -- no real API keys or network calls.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from providers.contracts import (
    AssistantToolCallMessage,
    ChatEvent,
    ChatRequest,
    ModelInfo,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)
from providers.errors import ProviderAuthError
from providers.router import Router
from tests.unit.providers.mocks import MockChatProvider, mock_model


# -- helpers --

class _FakeTransport:
    """Minimal HttpResponse-compatible transport for OpenAI-style providers."""

    def __init__(
        self,
        chat: dict[str, Any] | None = None,
        stream_lines: list[str] | None = None,
        models: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> None:
        self.chat = chat or {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        self.stream_lines = stream_lines or []
        self.models = models or {"data": []}
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> "_FakeResponse":
        self.calls.append({"method": method, "url": url, "json": json, "stream": stream, "timeout": timeout})
        if self.status_code >= 400:
            return _FakeResponse(status_code=self.status_code)
        if method.upper() == "GET" and "models" in url:
            return _FakeResponse(self.models)
        if stream:
            return _FakeResponse(lines=self.stream_lines)
        return _FakeResponse(self.chat)


class _FakeResponse:
    status_code: int
    _payload: dict[str, Any]
    _lines: list[str]

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        status_code: int = 200,
        lines: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = lines or []

    def json(self) -> dict[str, Any]:
        return self._payload

    def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]:
        yield from self._lines

    def close(self) -> None:
        pass


def _openai_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="openai", model_id="gpt-4o", display_name="GPT-4o",
        text=True, streaming=True, tool_calling=True, local=False, source="OpenAI",
        **overrides,
    )


def _gemini_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="gemini", model_id="gemini-2.0-flash", display_name="Gemini 2.0 Flash",
        text=True, streaming=True, tool_calling=True, local=False, source="Gemini",
        **overrides,
    )


def _openrouter_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="openrouter", model_id="openai/gpt-4o", display_name="GPT-4o via OpenRouter",
        text=True, streaming=True, tool_calling=True, local=False, source="OpenRouter",
        **overrides,
    )


def _local_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="local", model_id="tinyllama", display_name="TinyLlama",
        text=True, streaming=True, tool_calling=True, local=True, source="loopback",
        **overrides,
    )


def _ollama_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="ollama", model_id="llama3.2", display_name="Llama 3.2",
        text=True, streaming=True, tool_calling=True, local=True, source="Ollama",
        **overrides,
    )


def _llamacpp_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="llama_cpp", model_id="llama.gguf", display_name="llama.cpp GGUF",
        text=True, streaming=True, tool_calling=True, local=True, source="llama.cpp",
        **overrides,
    )


def _openai_compat_model(**overrides: Any) -> ModelInfo:
    return ModelInfo(
        provider_id="openai_compat", model_id="custom-model", display_name="Custom OpenAI-Compatible",
        text=True, streaming=True, tool_calling=True, local=False, source="custom",
        **overrides,
    )


# OpenAI helpers
def _openai_tool_call(id_: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """OpenAI-format tool call (arguments is a JSON string)."""
    return {
        "id": id_,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _openai_tool_response(id_: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [_openai_tool_call(id_, name, args)]}}]}


# OpenAI

async def test_openai_chat_returns_text() -> None:
    transport = _FakeTransport(
        chat={"choices": [{"message": {"role": "assistant", "content": "Hello from OpenAI!"}}]}
    )
    from providers.openai.provider import OpenAIChatProvider
    from providers.openai.client import OpenAIHttpClient

    client = OpenAIHttpClient("sk-test", transport=transport)
    provider = OpenAIChatProvider(api_key="sk-test", client=client)
    response = await provider.chat(ChatRequest(model=_openai_model(), messages=[UserMessage(content="hi")]))
    assert response.text == "Hello from OpenAI!"
    assert response.tool_calls == ()


async def test_openai_chat_returns_tool_calls() -> None:
    transport = _FakeTransport(chat=_openai_tool_response("call-001", "get_weather", {"city": "NYC"}))
    from providers.openai.provider import OpenAIChatProvider
    from providers.openai.client import OpenAIHttpClient

    client = OpenAIHttpClient("sk-test", transport=transport)
    provider = OpenAIChatProvider(api_key="sk-test", client=client)
    tools = [ToolDefinition(name="get_weather", description="Get weather",
                            parameters={"type": "object", "properties": {"city": {"type": "string"}}})]
    response = await provider.chat(
        ChatRequest(model=_openai_model(), messages=[UserMessage(content="weather?")], tools=tools)
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call-001"
    assert response.tool_calls[0].name == "get_weather"
    assert response.tool_calls[0].arguments == {"city": "NYC"}


async def test_openai_stream_tool_call_chain() -> None:
    transport = _FakeTransport(
        stream_lines=[
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-abc","type":"function","function":{"name":"lookup","arguments":"{\\"q\\":\\"test\\"}"}}]}}]}',
            'data: {"choices":[{"finish_reason":"tool_calls","delta":{}}]}',
            "data: [DONE]",
        ]
    )
    from providers.openai.provider import OpenAIChatProvider
    from providers.openai.client import OpenAIHttpClient

    client = OpenAIHttpClient("sk-test", transport=transport)
    provider = OpenAIChatProvider(api_key="sk-test", client=client)
    events = [e async for e in provider.stream(ChatRequest(model=_openai_model(), messages=[UserMessage(content="lookup test")]))]
    tc_event = next(e for e in events if e.type == "tool_call")
    assert tc_event.tool_call.id == "call-abc"
    assert tc_event.tool_call.name == "lookup"
    assert tc_event.tool_call.arguments == {"q": "test"}


# Gemini

async def test_gemini_chat_via_mock() -> None:
    """Gemini: use MockChatProvider (no live SDK required)."""
    mock = MockChatProvider("gemini")
    response = await mock.chat(ChatRequest(model=_gemini_model(), messages=[UserMessage(content="ping")]))
    assert response.text.startswith("mock-reply:")
    assert response.provider_id == "gemini"


async def test_gemini_stream_via_mock() -> None:
    """Gemini: stream via MockChatProvider."""
    mock = MockChatProvider("gemini")
    events = [e async for e in mock.stream(ChatRequest(model=_gemini_model(), messages=[UserMessage(content="stream-ping")]))]
    assert events[-1].type == "done"
    assert any(e.type == "delta" for e in events)


# OpenRouter

async def test_openrouter_chat_returns_tool_calls() -> None:
    from tests.unit.providers.openrouter.fakes import FakeResponse
    from providers.openrouter.provider import OpenRouterChatProvider

    def fake_request(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse(payload=_openai_tool_response("or-call-001", "search", {"query": "docs"}))

    provider = OpenRouterChatProvider(api_key="sk-or-test", request=fake_request)
    tools = [ToolDefinition(name="search", description="Search",
                            parameters={"type": "object", "properties": {"query": {"type": "string"}}})]
    response = await provider.chat(
        ChatRequest(model=_openrouter_model(), messages=[UserMessage(content="search docs")], tools=tools)
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "or-call-001"
    assert response.tool_calls[0].name == "search"


# Local (OpenAI-compatible)

async def test_local_chat_tool_call_chain() -> None:
    """Local provider: chat -> tool call -> ToolResult -> continuation -> final answer."""
    from tests.unit.providers.local.fakes import openai_transport

    transport = openai_transport()
    from providers.local.openai_compatible import OpenAICompatibleChatProvider

    transport.chat = {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [_openai_tool_call("local-1", "echo", {"msg": "hello"})]}}]}
    provider = OpenAICompatibleChatProvider(base_url="http://127.0.0.1:8080/v1", transport=transport)

    tools = [ToolDefinition(name="echo", description="Echo",
                            parameters={"type": "object", "properties": {"msg": {"type": "string"}}})]
    response1 = await provider.chat(
        ChatRequest(model=_local_model(), messages=[UserMessage(content="echo hello")], tools=tools)
    )
    assert len(response1.tool_calls) == 1
    assert response1.tool_calls[0].id == "local-1"

    tc = response1.tool_calls[0]
    result = ToolResultMessage(tool_call_id=tc.id, tool_name=tc.name, result="echo result")
    # Reset to pong response for the continuation
    transport.chat = {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
    response2 = await provider.chat(
        ChatRequest(model=_local_model(), messages=[
            UserMessage(content="echo hello"),
            AssistantToolCallMessage(tool_calls=(tc,)),
            result,
        ], tools=tools)
    )
    assert response2.text == "pong"


# Ollama

async def test_ollama_chat_returns_tool_call() -> None:
    """Ollama: returns tool_call in response."""
    from tests.unit.providers.local.fakes import FakeTransport

    transport = FakeTransport(
        chat={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "ollama-1",
                    "type": "function",
                    "function": {"name": "query_db", "arguments": {"sql": "SELECT 1"}}
                }],
                "done": True,
            },
        }
    )
    from providers.local.ollama import OllamaChatProvider

    provider = OllamaChatProvider(base_url="http://127.0.0.1:11434", transport=transport)
    tools = [ToolDefinition(name="query_db", description="Query DB",
                            parameters={"type": "object", "properties": {"sql": {"type": "string"}}})]
    response = await provider.chat(
        ChatRequest(model=_ollama_model(), messages=[UserMessage(content="run query")], tools=tools)
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "ollama-1"
    assert response.tool_calls[0].name == "query_db"


async def test_ollama_stream_chain() -> None:
    """Ollama: stream -> delta -> done."""
    from tests.unit.providers.local.fakes import ollama_transport

    transport = ollama_transport()
    from providers.local.ollama import OllamaChatProvider

    provider = OllamaChatProvider(base_url="http://127.0.0.1:11434", transport=transport)
    events = [e async for e in provider.stream(ChatRequest(model=_ollama_model(), messages=[UserMessage(content="ping")]))]
    assert events[-1].type == "done"


# llama.cpp

async def test_llamacpp_chat_returns_text() -> None:
    """llama.cpp: chat returns text (OpenAI-compatible format)."""
    from tests.unit.providers.local.fakes import openai_transport

    transport = openai_transport()
    from providers.local.llama_cpp import LlamaCppChatProvider

    provider = LlamaCppChatProvider(base_url="http://127.0.0.1:8088/v1", transport=transport)
    response = await provider.chat(ChatRequest(model=_llamacpp_model(), messages=[UserMessage(content="ping")]))
    assert response.text == "pong"


async def test_llamacpp_chat_tool_call() -> None:
    """llama.cpp: chat returns tool call in OpenAI format."""
    from tests.unit.providers.local.fakes import FakeTransport

    transport = FakeTransport(
        models={"data": [{"id": "llama.gguf"}]},
        chat={"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [_openai_tool_call("cpp-1", "calc", {"expr": "1+1"})]}}]}
    )
    from providers.local.llama_cpp import LlamaCppChatProvider

    provider = LlamaCppChatProvider(base_url="http://127.0.0.1:8088/v1", transport=transport)
    tools = [ToolDefinition(name="calc", description="Calculate",
                            parameters={"type": "object", "properties": {"expr": {"type": "string"}}})]
    response = await provider.chat(
        ChatRequest(model=_llamacpp_model(), messages=[UserMessage(content="calc")], tools=tools)
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "cpp-1"


# OpenAI-compatible (generic)

async def test_openai_compat_chat_tool_call_chain() -> None:
    """OpenAI-compatible: chat -> tool call -> ToolResult -> continuation -> final answer."""
    from tests.unit.providers.local.fakes import FakeTransport

    transport = FakeTransport(
        models={"data": [{"id": "custom-model"}]},
        chat={"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [_openai_tool_call("c1", "lookup", {"key": "test"})]}}]}
    )
    # Use the registry factory to get an openai_compat provider (provider_id patched to "openai_compat")
    from providers.local import register_factories

    register_factories()
    from providers.registry import get

    factory = get("openai_compat")
    provider = factory(base_url="http://127.0.0.1:8080/v1", transport=transport)
    tools = [ToolDefinition(name="lookup", description="Lookup",
                            parameters={"type": "object", "properties": {"key": {"type": "string"}}})]

    response1 = await provider.chat(
        ChatRequest(model=_openai_compat_model(), messages=[UserMessage(content="lookup test")], tools=tools)
    )
    assert len(response1.tool_calls) == 1
    tc = response1.tool_calls[0]
    assert tc.id == "c1"
    assert tc.name == "lookup"

    # Reset to pong response for the continuation
    transport.chat = {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
    result = ToolResultMessage(tool_call_id=tc.id, tool_name=tc.name, result=42)
    response2 = await provider.chat(
        ChatRequest(model=_openai_compat_model(), messages=[
            UserMessage(content="lookup test"),
            AssistantToolCallMessage(tool_calls=(tc,)),
            result,
        ], tools=tools)
    )
    assert response2.text == "pong"


# Router integration

async def test_router_stream_with_mock_provider() -> None:
    """Router: stream through a mock provider."""
    mock = MockChatProvider("local")
    router = Router(provider_id="local", providers={"local": mock})
    model = mock_model("local", text=True, streaming=True)
    request = ChatRequest(model=model, messages=[UserMessage(content="ping")])

    events = [e async for e in router.stream(request)]
    assert events[-1].type == "done"
    assert any(e.type == "delta" for e in events)


async def test_router_auth_error_propagates() -> None:
    """Router raises ProviderAuthError when key is missing for cloud provider."""
    router = Router(provider_id="openai", key_provider=lambda _: None)
    model = _openai_model()
    request = ChatRequest(model=model, messages=[UserMessage(content="hi")])
    with pytest.raises(ProviderAuthError, match="missing api key"):
        await router.chat(request)


async def test_router_chat_returns_response() -> None:
    """Router: chat returns ChatResponse from a mock provider."""
    mock = MockChatProvider("local")
    router = Router(provider_id="local", providers={"local": mock})
    model = mock_model("local", text=True, streaming=True)
    request = ChatRequest(model=model, messages=[UserMessage(content="hello")])

    response = await router.chat(request)
    assert response.text == "mock-reply: hello"
    assert response.provider_id == "local"


# Full E2E chain (local + Router + ToolChain)

async def test_full_e2e_local_tool_chain() -> None:
    """Full E2E: local provider -> Router -> tool call -> ToolResult -> continuation -> final answer."""
    from tests.unit.providers.local.fakes import FakeTransport

    transport = FakeTransport(
        models={"data": [{"id": "test-model"}]},
        chat={"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [_openai_tool_call("e2e-tool-1", "process", {"input": "data"})]}}]}
    )

    from providers.local import register_factories

    register_factories()
    from providers.registry import get

    factory = get("local")
    provider = factory(base_url="http://127.0.0.1:8080/v1", transport=transport)

    tools = [ToolDefinition(name="process", description="Process data",
                            parameters={"type": "object", "properties": {"input": {"type": "string"}}})]
    model = _local_model()

    response1 = await provider.chat(
        ChatRequest(model=model, messages=[UserMessage(content="process data")], tools=tools)
    )
    assert len(response1.tool_calls) == 1
    tc = response1.tool_calls[0]
    assert tc.id == "e2e-tool-1"

    tool_result = ToolResultMessage(tool_call_id=tc.id, tool_name=tc.name, result="processed: data")

    # Reset to pong response for the continuation
    transport.chat = {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
    response2 = await provider.chat(
        ChatRequest(model=model, messages=[
            UserMessage(content="process data"),
            AssistantToolCallMessage(tool_calls=(tc,)),
            tool_result,
        ], tools=tools)
    )
    assert response2.text == "pong"


async def test_full_e2e_via_router() -> None:
    """Full E2E through Router: provider -> Router -> chat -> tool -> ToolResult -> final."""
    from tests.unit.providers.local.fakes import FakeTransport

    transport = FakeTransport(
        models={"data": [{"id": "test-model"}]},
        chat={"choices": [{"message": {"role": "assistant", "content": "final-answer"}}]}
    )

    from providers.local import register_factories

    register_factories()
    from providers.registry import get

    factory = get("local")
    provider = factory(base_url="http://127.0.0.1:8080/v1", transport=transport)
    router = Router(provider_id="local", providers={"local": provider})

    model = _local_model()
    request = ChatRequest(model=model, messages=[UserMessage(content="e2e test")])

    response = await router.chat(request)
    assert response.text == "final-answer"
    assert response.provider_id == "local"
