from __future__ import annotations

import pytest

from providers.contracts import ChatEvent, ChatMessage, ChatRequest, ModelInfo
from providers.errors import CapabilityError, ProviderOfflineError
from providers.local import (
    LlamaCppChatProvider,
    OllamaChatProvider,
    OpenAICompatibleChatProvider,
)

from tests.unit.providers.local.fakes import (
    FakeTransport,
    ollama_transport,
    openai_transport,
)


def _text_model(provider_id: str, model_id: str = "tinyllama") -> ModelInfo:
    return ModelInfo(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        text=True,
        streaming=True,
        local=True,
    )


def _request(model: ModelInfo, role: str = "chat") -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="ping"),),
        role=role,
    )


@pytest.mark.parametrize(
    ("factory", "make_transport", "models_path"),
    (
        (OpenAICompatibleChatProvider, openai_transport, "/v1/models"),
        (OllamaChatProvider, ollama_transport, "/api/tags"),
        (LlamaCppChatProvider, openai_transport, "/v1/models"),
    ),
)
async def test_list_models_hits_mocked_catalog(
    factory, make_transport, models_path: str
) -> None:
    transport = make_transport()
    provider = factory(transport=transport)
    models = await provider.list_models()
    assert models
    assert all(item.local is True for item in models)
    assert all(item.provider_id == factory.provider_id for item in models)
    assert any(models_path in str(call["url"]) for call in transport.calls)
    assert all("example.com" not in str(call["url"]) for call in transport.calls)


@pytest.mark.parametrize(
    ("factory", "make_transport"),
    (
        (OpenAICompatibleChatProvider, openai_transport),
        (OllamaChatProvider, ollama_transport),
        (LlamaCppChatProvider, openai_transport),
    ),
)
async def test_chat_and_stream_use_mocked_transport(factory, make_transport) -> None:
    transport = make_transport()
    provider = factory(transport=transport)
    request = _request(_text_model(factory.provider_id))

    response = await provider.chat(request)
    assert response.text == "pong"
    assert response.provider_id == factory.provider_id
    assert response.model_id == "tinyllama"

    events = [event async for event in provider.stream(request)]
    assert events
    assert all(isinstance(event, ChatEvent) for event in events)
    assert events[-1] == ChatEvent(type="done")
    deltas = [event.text for event in events if event.type == "delta"]
    assert "".join(deltas) == "pong"
    assert any(call["stream"] is True for call in transport.calls)


@pytest.mark.parametrize(
    "factory",
    (
        OpenAICompatibleChatProvider,
        OllamaChatProvider,
        LlamaCppChatProvider,
    ),
)
async def test_capability_reject_happens_before_http(factory) -> None:
    transport = FakeTransport()
    provider = factory(transport=transport)
    model = ModelInfo(
        provider_id=factory.provider_id,
        model_id="vision-only",
        display_name="vision-only",
        text=False,
        vision=True,
        local=True,
    )
    request = _request(model, role="chat")
    with pytest.raises(CapabilityError) as exc_info:
        await provider.chat(request)
    assert transport.calls == []
    assert exc_info.value.role == "chat"

    with pytest.raises(CapabilityError, match="chat"):
        async for _event in provider.stream(request):
            pytest.fail("stream must not yield after a capability failure")
    assert transport.calls == []


async def test_local_failure_does_not_fall_back_to_cloud() -> None:
    transport = FakeTransport(error=OSError("connection refused"))
    provider = OpenAICompatibleChatProvider(transport=transport)
    request = _request(_text_model("local"))
    with pytest.raises(ProviderOfflineError, match="unreachable"):
        await provider.chat(request)
    assert len(transport.calls) == 1
    url = str(transport.calls[0]["url"])
    assert "127.0.0.1" in url
    assert "openai.com" not in url
    assert "openrouter.ai" not in url
    assert "example.com" not in url


async def test_validate_is_ok_when_catalog_is_mocked() -> None:
    provider = OpenAICompatibleChatProvider(transport=openai_transport())
    status = await provider.validate()
    assert status.ok is True
    assert status.provider_id == "local"


async def test_optional_key_is_not_required_for_validate() -> None:
    provider = OllamaChatProvider(api_key=None, transport=ollama_transport())
    status = await provider.validate()
    assert status.ok is True
    assert status.provider_id == "ollama"
