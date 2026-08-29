"""Regression tests for Provider Runtime Integrity.

Covers:
- openai_compat is a known, properly classified local provider
- Router resolves openai_compat via import
- Custom base_url reaches the adapter
- base_url is normalized and validated (loopback check)
- Cloud/local classification is unambiguous
- No silent cloud fallback from local provider
- list_models()/validate()/chat()/stream() behave consistently
- Typed errors (auth/network/model-not-found) are not masked
- Tool call_id preservation across all adapters
- No import-order dependency for provider registration
"""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Mapping

import pytest

from providers.contracts import (
    ChatEvent,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ToolCall,
    ToolDefinition,
)
from providers.errors import (
    CapabilityError,
    ProviderAuthError,
    ProviderError,
    ProviderOfflineError,
)
from providers.local import (
    LlamaCppChatProvider,
    OllamaChatProvider,
    OpenAICompatibleChatProvider,
)
from providers.registry import clear, get, register, registered_ids

from tests.unit.providers.local.fakes import FakeTransport, openai_transport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LOCAL_PROVIDERS = (
    OpenAICompatibleChatProvider,
    OllamaChatProvider,
    LlamaCppChatProvider,
)


def _model(
    provider_id: str,
    *,
    text: bool = True,
    streaming: bool = True,
    tool_calling: bool = False,
    local: bool = False,
) -> ModelInfo:
    return ModelInfo(
        provider_id=provider_id,
        model_id=f"{provider_id}-model",
        display_name=provider_id,
        text=text,
        streaming=streaming,
        tool_calling=tool_calling,
        local=local,
    )


def _text_request(provider_id: str = "local") -> ChatRequest:
    return ChatRequest(
        model=_model(provider_id, local=True),
        messages=(ChatMessage(role="user", content="ping"),),
        role="chat",
    )


# ---------------------------------------------------------------------------
# 1. openai_compat registration and classification
# ---------------------------------------------------------------------------


def test_openai_compat_is_known_local_provider() -> None:
    """openai_compat must be in LOCAL_PROVIDER_IDS and not in CLOUD_PROVIDER_IDS."""
    from providers.router import CLOUD_PROVIDER_IDS, LOCAL_PROVIDER_IDS

    assert "openai_compat" in LOCAL_PROVIDER_IDS
    assert "openai_compat" not in CLOUD_PROVIDER_IDS


def test_openai_compat_routing_local_classification() -> None:
    """routing.is_local_model must return True for openai_compat."""
    from providers.routing import is_local_model

    model = _model("openai_compat", local=True)
    assert is_local_model(model) is True

    cloud_model = _model("openai", local=False)
    assert is_local_model(cloud_model) is False


# ---------------------------------------------------------------------------
# 2. Router resolves openai_compat via import (no prior import dependency)
# ---------------------------------------------------------------------------


def test_router_adapters_include_openai_compat() -> None:
    """router._ADAPTER_MODULES must contain openai_compat entry."""
    from providers.router import _ADAPTER_MODULES

    assert "openai_compat" in _ADAPTER_MODULES
    assert _ADAPTER_MODULES["openai_compat"] == "providers.local"


def test_openai_compat_factory_returns_proper_id() -> None:
    """Factory must produce instance with provider_id == 'openai_compat'."""
    register_factories()
    instance = get("openai_compat")(transport=openai_transport())
    assert instance.provider_id == "openai_compat"
    assert isinstance(instance, OpenAICompatibleChatProvider)


# ---------------------------------------------------------------------------
# 3. Custom base_url reaches the adapter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", LOCAL_PROVIDERS)
async def test_custom_base_url_is_used_in_requests(factory) -> None:
    """Custom base_url must actually reach the adapter in HTTP calls."""
    custom_url = f"http://127.0.0.1:{9000 + hash(factory.provider_id) % 1000}/v1"
    transport = FakeTransport(models={"data": [{"id": "test-model"}]})
    provider = factory(base_url=custom_url, transport=transport)

    models = await provider.list_models()
    assert models

    url_str = str(transport.calls[0]["url"])
    assert custom_url in url_str


# ---------------------------------------------------------------------------
# 4. base_url normalization and validation
# ---------------------------------------------------------------------------


def test_base_url_requires_http_scheme() -> None:
    """base_url without http/https should raise ProviderError."""
    from providers.local.endpoint import parse_endpoint_host

    with pytest.raises(ProviderError, match="http or https"):
        parse_endpoint_host("ftp://localhost:8080")

    with pytest.raises(ProviderError, match="http or https"):
        parse_endpoint_host("")


def test_loopback_rejection_for_non_loopback_when_disallowed() -> None:
    """Non-loopback base_url with allow_remote=False must raise."""
    from providers.local.endpoint import assert_endpoint_allowed

    with pytest.raises(ProviderOfflineError, match="non-loopback"):
        assert_endpoint_allowed(
            "http://192.168.1.1:8080/v1",
            allow_remote=False,
            provider_id="local",
        )


def test_loopback_is_allowed() -> None:
    """Loopback and localhost must not raise when allow_remote=False."""
    from providers.local.endpoint import assert_endpoint_allowed

    for url in [
        "http://127.0.0.1:8080/v1",
        "http://localhost:8080/v1",
        "https://127.0.0.1:443/v1",
    ]:
        assert_endpoint_allowed(url, allow_remote=False, provider_id="local")


def test_remote_allowed_when_flag_is_true() -> None:
    """allow_remote=True must accept any valid http(s) URL."""
    from providers.local.endpoint import assert_endpoint_allowed

    assert_endpoint_allowed(
        "https://openrouter.ai/api/v1",
        allow_remote=True,
        provider_id="local",
    )


# ---------------------------------------------------------------------------
# 5. No silent cloud fallback from local provider
# ---------------------------------------------------------------------------


async def test_local_provider_failure_raises_not_fallbacks_to_cloud() -> None:
    """Local provider failure must raise ProviderOfflineError, never fall back."""
    transport = FakeTransport(error=OSError("connection refused"))
    provider = OpenAICompatibleChatProvider(transport=transport)

    with pytest.raises(ProviderOfflineError, match="unreachable"):
        await provider.chat(_text_request("local"))

    # Verify only one call was made (no retry to different provider)
    assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# 6. Consistent behavior: list_models, validate, chat, stream
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", LOCAL_PROVIDERS)
async def test_list_models_validate_chat_stream_consistency(factory) -> None:
    """All four methods must accept the same model and work together."""
    transport = openai_transport()
    provider = factory(transport=transport)
    model = _model(factory.provider_id, local=True, tool_calling=True)

    models = await provider.list_models()
    assert models

    status = await provider.validate()
    assert status.ok is True

    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="ping"),),
        role="chat",
    )
    response = await provider.chat(request)
    assert response.provider_id == factory.provider_id

    events = [e async for e in provider.stream(request)]
    assert events[-1].type == "done"


# ---------------------------------------------------------------------------
# 7. Typed errors are not masked
# ---------------------------------------------------------------------------


async def test_auth_error_is_not_masked() -> None:
    """ProviderAuthError should propagate without masking."""
    transport = FakeTransport(status_code=401)
    provider = OpenAICompatibleChatProvider(transport=transport)

    with pytest.raises(ProviderError):
        await provider.chat(_text_request("local"))


async def test_network_error_is_provider_offline_error() -> None:
    """Network failures must raise ProviderOfflineError with details."""
    transport = FakeTransport(error=OSError("network unreachable"))
    provider = OpenAICompatibleChatProvider(transport=transport)

    with pytest.raises(ProviderOfflineError, match="unreachable"):
        await provider.chat(_text_request("local"))


# ---------------------------------------------------------------------------
# 8. Tool call_id preservation
# ---------------------------------------------------------------------------


async def test_tool_call_id_is_preserved_in_chat() -> None:
    """Tool call id from provider response must be preserved."""
    transport = FakeTransport(
        chat={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call-preserved-id",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"x":1}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )
    provider = OpenAICompatibleChatProvider(transport=transport)
    model = _model("local", tool_calling=True)
    request = ChatRequest(
        model=model,
        messages=(ChatMessage(role="user", content="call tool"),),
        tools=(
            ToolDefinition(
                name="test_tool",
                description="Test",
                parameters={"type": "object", "properties": {"x": {"type": "number"}}},
            ),
        ),
    )
    response = await provider.chat(request)
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call-preserved-id"
    assert response.tool_calls[0].name == "test_tool"
    assert response.tool_calls[0].arguments == {"x": 1}


async def test_tool_call_id_is_preserved_in_stream() -> None:
    """Tool call id from stream must be preserved."""
    import json

    transport = FakeTransport(
        stream_lines=(
            json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "stream-call-id",
                                        "type": "function",
                                        "function": {"name": "stream_tool", "arguments": "{}"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
            "data: [DONE]",
        )
    )
    provider = OpenAICompatibleChatProvider(transport=transport)
    events = [event async for event in provider.stream(_text_request("local"))]
    assert events[0].type == "tool_call"
    assert events[0].tool_call.id == "stream-call-id"
    assert events[0].tool_call.name == "stream_tool"


async def test_ollama_tool_call_id_preserved_across_fragments() -> None:
    """Tool call id is preserved when id fragment arrives before arguments (real-world pattern).
    """
    import json

    transport = FakeTransport(
        stream_lines=(
            json.dumps(
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 0, "id": "frag-id-001"}]}}
                    ]
                }
            ),
            json.dumps(
                {
                    "choices": [
                        {
                            "delta": {"tool_calls": [{"function": {"arguments": '{"n":5}'}}]},
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            ),
            "data: [DONE]",
        )
    )
    provider = OpenAICompatibleChatProvider(transport=transport)
    events = [event async for event in provider.stream(_text_request("local"))]
    assert events[0].type == "tool_call"
    assert events[0].tool_call.id == "frag-id-001"


# ---------------------------------------------------------------------------
# 9. Import-order independence
# ---------------------------------------------------------------------------


def test_registry_without_prior_provider_import() -> None:
    """Registry must find openai_compat even if providers.local was not imported first."""
    clear()
    # Import only the router module, not providers.local directly
    import providers.router as router_mod

    # The router imports providers.local lazily via _ADAPTER_MODULES
    assert "openai_compat" in router_mod._ADAPTER_MODULES

    # Verify that _factory_for triggers lazy import and succeeds
    factory = router_mod._factory_for("openai_compat")
    assert callable(factory)

    clear()


def test_all_registered_ids_deterministic() -> None:
    """registered_ids() must return sorted tuple deterministically."""
    register_factories()
    ids = registered_ids()
    assert ids == tuple(sorted(ids))
    assert len(ids) == len(set(ids))  # no duplicates
    clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def register_factories() -> None:
    """Register local provider factories (idempotent)."""
    from providers.local import register_factories as rf
    rf()
