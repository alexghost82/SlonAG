from __future__ import annotations

import importlib
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from providers.contracts import (
    ChatEvent,
    ChatMessage,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ModelInfo,
)
from providers.errors import CapabilityError, ProviderAuthError
from providers.openai.client import OpenAIHttpClient
from providers.openai.provider import (
    OpenAIChatProvider,
    conservative_capabilities,
)
from providers.registry import get, register, registered_ids

TEST_KEY = "unit-test-openai-key"
TEXT_MODEL_ID = "gpt-3.5-turbo"


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        status_code: int = 200,
        lines: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._lines = list(lines or [])
        self.closed = False

    def json(self) -> dict[str, Any]:
        return self._payload

    def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]:
        yield from self._lines

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chat_payload: dict[str, Any] = {
            "choices": [{"message": {"content": "hello"}}]
        }
        self.models_payload: dict[str, Any] = {
            "data": [{"id": TEXT_MODEL_ID, "owned_by": "openai"}]
        }
        self.stream_lines = [
            'data: {"choices":[{"delta":{"content":"hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
        ]
        self.status_code = 200

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": dict(json) if json is not None else None,
                "stream": stream,
                "timeout": timeout,
            }
        )
        if self.status_code >= 400:
            return FakeResponse(status_code=self.status_code)
        if method == "GET" and url.endswith("/models"):
            return FakeResponse(self.models_payload)
        if stream:
            return FakeResponse(lines=self.stream_lines)
        return FakeResponse(self.chat_payload)


def _text_model() -> ModelInfo:
    return ModelInfo(
        provider_id="openai",
        model_id=TEXT_MODEL_ID,
        display_name=TEXT_MODEL_ID,
        text=True,
        streaming=True,
    )


def _request(
    model: ModelInfo | None = None, *, role: str = "chat"
) -> ChatRequest:
    return ChatRequest(
        model=model or _text_model(),
        messages=(ChatMessage(role="user", content="ping"),),
        role=role,
    )


def _provider(
    transport: FakeTransport | None = None,
    *,
    api_key: str | None = TEST_KEY,
) -> tuple[OpenAIChatProvider, FakeTransport]:
    fake = transport or FakeTransport()
    client = OpenAIHttpClient(api_key or "unused", transport=fake)
    return OpenAIChatProvider(api_key=api_key, client=client), fake


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("live network is forbidden in unit tests")

    monkeypatch.setattr(
        "providers.openai.client.RequestsTransport.request",
        blocked,
    )


async def test_missing_key_validate_is_not_ok_and_skips_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_network(monkeypatch)
    provider = OpenAIChatProvider(api_key=None)

    status = await provider.validate()

    assert status.ok is False
    assert status.provider_id == "openai"
    assert "missing" in status.message


async def test_blank_key_is_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _block_network(monkeypatch)
    provider = OpenAIChatProvider(api_key="   ")

    status = await provider.validate()

    assert status.ok is False
    with pytest.raises(ProviderAuthError, match="missing"):
        await provider.chat(_request())


async def test_capability_reject_happens_before_http() -> None:
    provider, transport = _provider()

    with pytest.raises(CapabilityError) as exc_info:
        await provider.chat(_request(role="vision"))

    assert exc_info.value.role == "vision"
    assert exc_info.value.model_id == TEXT_MODEL_ID
    assert transport.calls == []


async def test_stream_capability_reject_happens_before_http() -> None:
    provider, transport = _provider()

    with pytest.raises(CapabilityError, match="vision"):
        async for _event in provider.stream(_request(role="vision")):
            pytest.fail("stream must not yield after a capability failure")

    assert transport.calls == []


async def test_chat_returns_response_shape() -> None:
    provider, transport = _provider()

    response = await provider.chat(_request())

    assert isinstance(response, ChatResponse)
    assert response.text == "hello"
    assert response.provider_id == "openai"
    assert response.model_id == TEXT_MODEL_ID
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/chat/completions")
    assert call["json"]["model"] == TEXT_MODEL_ID
    assert call["json"]["stream"] is False


async def test_stream_yields_delta_then_done() -> None:
    provider, transport = _provider()

    events = [event async for event in provider.stream(_request())]

    assert events
    assert all(isinstance(event, ChatEvent) for event in events)
    assert {event.type for event in events} <= {"delta", "done"}
    assert events[-1].type == "done"
    assert events[-1].text == ""
    deltas = [event.text for event in events if event.type == "delta"]
    assert "".join(deltas) == "hello"
    assert len(transport.calls) == 1
    assert transport.calls[0]["json"]["model"] == TEXT_MODEL_ID
    assert transport.calls[0]["json"]["stream"] is True


def test_factory_is_registered_as_openai() -> None:
    import providers.openai as openai_pkg
    import providers.openai.provider as provider_mod

    importlib.reload(provider_mod)
    importlib.reload(openai_pkg)
    register("openai", OpenAIChatProvider)

    assert "openai" in registered_ids()
    factory = get("openai")
    provider = factory(api_key=TEST_KEY)
    assert isinstance(provider, ChatProvider)
    assert isinstance(provider, OpenAIChatProvider)


async def test_text_only_model_capabilities_are_conservative() -> None:
    provider, transport = _provider()

    models = await provider.list_models()

    assert len(models) == 1
    model = models[0]
    assert model.provider_id == "openai"
    assert model.model_id == TEXT_MODEL_ID
    assert model.text is True
    assert model.streaming is True
    assert model.vision is False
    assert model.audio_input is False
    assert model.audio_output is False
    assert model.tool_calling is False
    assert model.structured_output is False
    assert model.embeddings is False
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"].endswith("/models")


def test_known_chat_model_does_not_claim_vision() -> None:
    flags = conservative_capabilities("gpt-4o")
    assert flags["text"] is True
    assert flags["vision"] is False
    assert flags["tool_calling"] is False


async def test_chat_sends_exactly_one_requested_model() -> None:
    provider, transport = _provider()
    other = ModelInfo(
        provider_id="openai",
        model_id="gpt-4.1-mini",
        display_name="gpt-4.1-mini",
        text=True,
        streaming=True,
    )

    await provider.chat(_request(other))

    assert [call["json"]["model"] for call in transport.calls] == [
        "gpt-4.1-mini"
    ]


async def test_default_base_url_is_openai_v1() -> None:
    provider, transport = _provider()
    await provider.chat(_request())
    assert transport.calls[0]["url"].startswith("https://api.openai.com/v1/")


async def test_base_url_is_injectable() -> None:
    transport = FakeTransport()
    client = OpenAIHttpClient(
        TEST_KEY,
        base_url="https://example.test/v1",
        transport=transport,
    )
    provider = OpenAIChatProvider(api_key=TEST_KEY, client=client)

    await provider.chat(_request())

    assert transport.calls[0]["url"] == (
        "https://example.test/v1/chat/completions"
    )


async def test_requests_transport_can_be_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = pytest.importorskip("requests")
    captured: dict[str, Any] = {}

    class FakeRequestsResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "via-requests"}}]}

        def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]:
            return iter(())

        def close(self) -> None:
            return None

    def fake_request(method: str, url: str, **kwargs: Any) -> FakeRequestsResponse:
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeRequestsResponse()

    monkeypatch.setattr(requests, "request", fake_request)
    provider = OpenAIChatProvider(api_key=TEST_KEY)

    response = await provider.chat(_request())

    assert response.text == "via-requests"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["json"]["model"] == TEXT_MODEL_ID
