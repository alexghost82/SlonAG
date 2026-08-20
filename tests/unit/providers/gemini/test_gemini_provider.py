from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest

from providers.contracts import (
    ChatMessage,
    ChatProvider,
    ChatRequest,
    ModelInfo,
    ToolCall,
    ToolDefinition,
)
from providers.errors import CapabilityError, ProviderAuthError, ProviderError
from providers.gemini.catalog import PROVIDER_ID
from providers.gemini.provider import GeminiChatProvider
from providers.registry import get


class FakeChunk:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeGeminiClient:
    """In-process stand-in for ``google.genai.Client``. No network I/O."""

    def __init__(self, text: str = "hello from gemini") -> None:
        self.reply = text
        self.generate_content_calls: list[dict[str, object]] = []
        self.generate_content_stream_calls: list[dict[str, object]] = []
        self.models = self

    def generate_content(self, **kwargs: object) -> FakeChunk:
        self.generate_content_calls.append(dict(kwargs))
        return FakeChunk(self.reply)

    def generate_content_stream(self, **kwargs: object) -> Iterator[FakeChunk]:
        self.generate_content_stream_calls.append(dict(kwargs))
        mid = max(1, len(self.reply) // 2)
        yield FakeChunk(self.reply[:mid])
        if self.reply[mid:]:
            yield FakeChunk(self.reply[mid:])


class ExplodingFactory:
    def __call__(self, api_key: str) -> FakeGeminiClient:
        raise AssertionError("google-genai client must not be constructed")


def _text_model(**overrides: object) -> ModelInfo:
    fields: dict[str, object] = {
        "provider_id": PROVIDER_ID,
        "model_id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "text": True,
        "streaming": True,
        "vision": False,
        "audio_input": False,
        "audio_output": False,
        "embeddings": False,
    }
    fields.update(overrides)
    return ModelInfo(**fields)  # type: ignore[arg-type]


def _request(model: ModelInfo, *, role: str = "chat") -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="ping"),),
        role=role,
    )


def test_package_import_registers_gemini_factory() -> None:
    import providers.gemini as gemini_pkg

    importlib.reload(gemini_pkg)
    factory = get("gemini")
    provider = factory(api_key="test-key-not-real")
    assert factory is gemini_pkg.GeminiChatProvider
    assert isinstance(provider, gemini_pkg.GeminiChatProvider)
    assert isinstance(provider, ChatProvider)


async def test_missing_key_validate_is_not_ok_and_skips_client() -> None:
    factory = ExplodingFactory()
    provider = GeminiChatProvider(api_key=None, client_factory=factory)
    status = await provider.validate()
    assert status.ok is False
    assert status.provider_id == "gemini"
    assert "missing" in status.message.lower()


async def test_blank_key_is_treated_as_missing() -> None:
    provider = GeminiChatProvider(api_key="   ", client_factory=ExplodingFactory())
    status = await provider.validate()
    assert status.ok is False


async def test_capability_reject_happens_before_chat_client_call() -> None:
    client = FakeGeminiClient()
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    request = _request(_text_model(text=False), role="chat")
    with pytest.raises(CapabilityError) as exc_info:
        await provider.chat(request)
    assert client.generate_content_calls == []
    assert exc_info.value.role == "chat"
    assert exc_info.value.model_id == "gemini-2.5-flash"
    assert exc_info.value.provider_id == "gemini"


async def test_capability_reject_happens_before_stream_client_call() -> None:
    client = FakeGeminiClient()
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    request = _request(_text_model(text=True, vision=False), role="vision")
    with pytest.raises(CapabilityError, match="vision"):
        async for _event in provider.stream(request):
            pytest.fail("stream must not yield after a capability failure")
    assert client.generate_content_stream_calls == []


async def test_chat_returns_chat_response() -> None:
    client = FakeGeminiClient(text="adapter reply")
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    response = await provider.chat(_request(_text_model()))
    assert response.text == "adapter reply"
    assert response.provider_id == "gemini"
    assert response.model_id == "gemini-2.5-flash"
    assert len(client.generate_content_calls) == 1
    assert client.generate_content_calls[0]["model"] == "gemini-2.5-flash"


async def test_stream_yields_delta_then_done() -> None:
    client = FakeGeminiClient(text="abcdef")
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    events = [event async for event in provider.stream(_request(_text_model()))]
    assert events
    assert events[-1].type == "done"
    assert events[-1].text == ""
    deltas = [event.text for event in events if event.type == "delta"]
    assert deltas
    assert "".join(deltas) == "abcdef"
    assert {event.type for event in events} <= {"delta", "done"}


async def test_stream_sends_tools_and_emits_native_function_call() -> None:
    class ToolChunk:
        text = ""
        function_calls = [
            type("Call", (), {"id": "g-1", "name": "lookup", "args": {"q": "x"}})()
        ]

    client = FakeGeminiClient()

    def stream(**kwargs: object):
        client.generate_content_stream_calls.append(dict(kwargs))
        yield ToolChunk()

    client.generate_content_stream = stream
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    request = ChatRequest(
        model=_text_model(tool_calling=True),
        messages=(ChatMessage(role="user", content="lookup"),),
        tools=(ToolDefinition("lookup", "Lookup", {"type": "object"}),),
    )
    events = [event async for event in provider.stream(request)]
    assert events[0].tool_call == ToolCall("g-1", "lookup", {"q": "x"})
    assert events[-1].type == "done"
    config = client.generate_content_stream_calls[0]["config"]
    assert config["tools"][0]["function_declarations"][0]["name"] == "lookup"


async def test_stream_rejects_duplicate_native_function_call_ids() -> None:
    class ToolChunk:
        text = ""

        def __init__(self, value: str) -> None:
            self.function_calls = [
                type(
                    "Call",
                    (),
                    {"id": "same", "name": "lookup", "args": {"q": value}},
                )()
            ]

    client = FakeGeminiClient()
    client.generate_content_stream = lambda **_kwargs: iter(
        (ToolChunk("first"), ToolChunk("second"))
    )
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    with pytest.raises(ProviderError, match="duplicate"):
        async for _event in provider.stream(_request(_text_model())):
            pass


async def test_list_models_uses_gemini_provider_id_and_honest_flags() -> None:
    provider = GeminiChatProvider(api_key=None, client_factory=ExplodingFactory())
    models = await provider.list_models()
    assert models
    assert all(model.provider_id == "gemini" for model in models)
    assert any(model.vision for model in models)
    assert any(not model.vision for model in models)
    assert all(not model.audio_input for model in models)
    assert all(not model.audio_output for model in models)
    assert any(model.embeddings and not model.text for model in models)


async def test_chat_without_key_raises_auth_error_after_capability_check() -> None:
    provider = GeminiChatProvider(api_key=None, client_factory=ExplodingFactory())
    with pytest.raises(ProviderAuthError, match="missing"):
        await provider.chat(_request(_text_model()))


async def test_chat_does_not_walk_fallback_models() -> None:
    client = FakeGeminiClient(text="only-this-model")
    provider = GeminiChatProvider(api_key="test-key-not-real", client=client)
    model = _text_model(model_id="gemini-2.5-pro")
    response = await provider.chat(_request(model))
    assert response.model_id == "gemini-2.5-pro"
    assert [call["model"] for call in client.generate_content_calls] == [
        "gemini-2.5-pro"
    ]
