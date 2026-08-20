from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from providers.capabilities import require_capability
from providers.contracts import (
    ChatEvent,
    ChatMessage,
    ChatProvider,
    ChatRequest,
    ModelInfo,
    ToolCall,
)
from providers.errors import CapabilityError, ProviderAuthError, ProviderError
from providers.openrouter import (
    OpenRouterChatProvider,
    RateLimitError,
    register_provider,
)
from providers.openrouter.catalog import parse_models_payload
from providers.openrouter.client import DEFAULT_API_URL, models_url_from_api_url
from providers.registry import get, registered_ids

from tests.unit.providers.openrouter.fakes import MODELS_FIXTURE, FakeResponse

PACKAGE_ROOT = Path(__file__).resolve().parents[4] / "providers" / "openrouter"


def test_default_api_url_is_openrouter_chat_completions() -> None:
    assert DEFAULT_API_URL == "https://openrouter.ai/api/v1/chat/completions"
    assert models_url_from_api_url(DEFAULT_API_URL) == "https://openrouter.ai/api/v1/models"


def test_registered_as_openrouter(clean_registry) -> None:
    register_provider()
    assert "openrouter" in registered_ids()
    factory = get("openrouter")
    provider = factory(api_key="test-key")
    assert isinstance(provider, OpenRouterChatProvider)
    assert isinstance(provider, ChatProvider)


def test_import_registers_openrouter(clean_registry) -> None:
    import providers.openrouter as package

    importlib.reload(package)
    assert "openrouter" in registered_ids()


async def test_missing_key_validate_not_ok() -> None:
    calls: list[object] = []

    def fake_request(*_args: object, **_kwargs: object) -> FakeResponse:
        calls.append(1)
        raise AssertionError("validate must not use HTTP when the key is missing")

    provider = OpenRouterChatProvider(request=fake_request)
    status = await provider.validate()
    assert status.ok is False
    assert status.provider_id == "openrouter"
    assert "missing" in status.message.lower()
    assert calls == []

    blank = OpenRouterChatProvider(api_key="   ", request=fake_request)
    blank_status = await blank.validate()
    assert blank_status.ok is False
    assert calls == []


async def test_missing_key_does_not_call_http() -> None:
    calls: list[object] = []

    def fake_request(*_args: object, **_kwargs: object) -> FakeResponse:
        calls.append(1)
        raise AssertionError("missing key must not open a socket")

    provider = OpenRouterChatProvider(api_key=None, request=fake_request)
    with pytest.raises(ProviderAuthError, match="missing api_key"):
        await provider.list_models()
    with pytest.raises(ProviderAuthError, match="missing api_key"):
        await provider.chat(
            ChatRequest(
                model=ModelInfo(
                    provider_id="openrouter",
                    model_id="x",
                    display_name="x",
                    text=True,
                ),
                messages=(ChatMessage(role="user", content="hi"),),
            )
        )
    assert calls == []


async def test_429_retry_after_does_not_try_second_model(
    chat_request: ChatRequest,
) -> None:
    models_seen: list[str] = []

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        payload = kwargs.get("json") or {}
        assert isinstance(payload, dict)
        models_seen.append(str(payload.get("model")))
        return FakeResponse(status_code=429, headers={"Retry-After": "17"})

    provider = OpenRouterChatProvider(api_key="test-key", request=fake_request)
    with pytest.raises(RateLimitError) as exc_info:
        await provider.chat(chat_request)

    error = exc_info.value
    assert isinstance(error, ProviderError)
    assert error.status_code == 429
    assert error.retry_after == 17.0
    assert error.retry_after_header == "17"
    assert "Retry-After=17" in str(error)
    assert models_seen == ["test/model"]


async def test_stream_429_does_not_switch_models(chat_request: ChatRequest) -> None:
    calls: list[str] = []

    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        payload = kwargs.get("json") or {}
        assert isinstance(payload, dict)
        calls.append(str(payload.get("model")))
        return FakeResponse(status_code=429, headers={"retry-after": "3"})

    provider = OpenRouterChatProvider(api_key="test-key", request=fake_request)
    with pytest.raises(RateLimitError) as exc_info:
        async for _event in provider.stream(chat_request):
            raise AssertionError("stream must stop on 429")

    assert exc_info.value.retry_after == 3.0
    assert calls == ["test/model"]


def test_catalog_parse_from_fixture_json() -> None:
    payload = json.loads(MODELS_FIXTURE.read_text(encoding="utf-8"))
    models = parse_models_payload(payload)
    assert models
    assert all(model.provider_id == "openrouter" for model in models)

    by_id = {model.model_id: model for model in models}

    text_model = by_id["meta-llama/llama-3.3-70b-instruct"]
    assert text_model.text is True
    assert text_model.streaming is True
    assert text_model.vision is False
    assert text_model.audio_input is False
    assert text_model.audio_output is False
    assert text_model.embeddings is False
    assert text_model.tool_calling is False
    assert text_model.context_length == 131072
    assert text_model.local is False

    vision = by_id["google/gemma-3-12b-it"]
    assert vision.vision is True
    assert vision.text is True
    assert vision.tool_calling is True

    embedding = by_id["openai/text-embedding-3-small"]
    assert embedding.embeddings is True
    assert embedding.text is False
    assert embedding.streaming is False
    assert embedding.vision is False


async def test_list_models_uses_mocked_models_endpoint() -> None:
    payload = json.loads(MODELS_FIXTURE.read_text(encoding="utf-8"))
    urls: list[str] = []

    def fake_request(method: str, url: str, **_kwargs: object) -> FakeResponse:
        urls.append(url)
        assert method == "GET"
        return FakeResponse(payload=payload)

    provider = OpenRouterChatProvider(
        api_key="test-key",
        api_url="https://example.test/api/v1/chat/completions",
        request=fake_request,
    )
    models = await provider.list_models()
    assert urls == ["https://example.test/api/v1/models"]
    assert {model.model_id for model in models} == {
        "meta-llama/llama-3.3-70b-instruct",
        "google/gemma-3-12b-it",
        "openai/text-embedding-3-small",
    }


async def test_chat_and_stream_event_shape(chat_request: ChatRequest) -> None:
    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        assert method == "POST"
        assert url == "https://example.test/api/v1/chat/completions"
        payload = kwargs.get("json") or {}
        assert isinstance(payload, dict)
        assert payload["model"] == "test/model"
        if payload.get("stream"):
            return FakeResponse(
                lines=[
                    'data: {"choices":[{"delta":{"content":"hel"}}]}',
                    'data: {"choices":[{"delta":{"content":"lo"}}]}',
                    "data: [DONE]",
                ]
            )
        return FakeResponse(
            payload={"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
        )

    provider = OpenRouterChatProvider(
        api_key="test-key",
        api_url="https://example.test/api/v1/chat/completions",
        request=fake_request,
    )
    response = await provider.chat(chat_request)
    assert response.text == "pong"
    assert response.provider_id == "openrouter"
    assert response.model_id == "test/model"

    events = [event async for event in provider.stream(chat_request)]
    assert events[0] == ChatEvent(type="delta", text="hel")
    assert events[1] == ChatEvent(type="delta", text="lo")
    assert events[-1] == ChatEvent(type="done")
    assert events[-1].text == ""


async def test_stream_assembles_fragmented_tool_call(chat_request: ChatRequest) -> None:
    def fake_request(method: str, url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse(lines=[
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"or-1",'
            '"function":{"name":"lookup","arguments":"{\\"q\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"\\"x\\"}"}}]},"finish_reason":"tool_calls"}]}',
            "data: [DONE]",
        ])

    provider = OpenRouterChatProvider(api_key="test-key", request=fake_request)
    events = [event async for event in provider.stream(chat_request)]
    assert [event.type for event in events] == ["tool_call", "done"]
    assert events[0].tool_call == ToolCall("or-1", "lookup", {"q": "x"})


async def test_capability_reject_before_http() -> None:
    calls: list[object] = []

    def fake_request(*_args: object, **_kwargs: object) -> FakeResponse:
        calls.append(1)
        raise AssertionError("capability failure must not reach HTTP")

    provider = OpenRouterChatProvider(api_key="test-key", request=fake_request)
    model = ModelInfo(
        provider_id="openrouter",
        model_id="vision-only",
        display_name="Vision only",
        text=False,
        vision=True,
    )
    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="hi"),),
        role="chat",
    )
    with pytest.raises(CapabilityError):
        require_capability(model, "chat")
    with pytest.raises(CapabilityError):
        await provider.chat(request)
    with pytest.raises(CapabilityError):
        async for _event in provider.stream(request):
            pass
    assert calls == []


def test_package_does_not_import_or_client_or_hide_fallback_list() -> None:
    forbidden = (
        "or_client",
        "TEXT_MODELS",
        "VISION_MODELS",
        "api_keys.json",
        "get_secret",
    )
    sources: list[str] = []
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        sources.append(text)
        for snippet in forbidden:
            assert snippet not in text, f"{path.name} must not mention {snippet}"
    joined = "\n".join(sources)
    assert "https://openrouter.ai/api/v1/chat/completions" in joined
