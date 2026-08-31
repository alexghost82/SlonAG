"""Provider runtime integrity tests.

Covers edge cases that the normal happy-path tests miss:
- Stream parser edge cases (empty lines, whitespace, partial data)
- Tool call ID deduplication across parsers
- Registry thread safety
- Router cache consistency
- Contract validation edge cases
- Error redaction completeness
- Endpoint security edge cases
- Missing __all__ exports
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from providers.capabilities import (
    KNOWN_ROLES,
    ROLE_CAPABILITY_FLAGS,
    require_capability,
    require_capabilities,
    require_provider_match,
    supports,
)
from providers.contracts import (
    AssistantMessage,
    AssistantToolCallMessage,
    ChatEvent,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConversationMessage,
    ModelInfo,
    ProviderStatus,
    SystemMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from providers.errors import (
    CapabilityError,
    ProviderAuthError,
    ProviderError,
    ProviderOfflineError,
    redact_secrets,
)
from providers.local.common import DEFAULT_LOCAL_BASE_URL
from providers.local.endpoint import (
    assert_endpoint_allowed,
    is_loopback_host,
    is_loopback_url,
    join_endpoint,
    origin_of,
    parse_endpoint_host,
)
from providers.openai.provider import OpenAIChatProvider, PROVIDER_ID
from providers.registry import clear, get, register, registered_ids
from providers.router import Router
from providers.routing import (
    CLOUD_PROVIDER_IDS,
    LOCAL_PROVIDER_IDS,
    ROUTING_MODES,
    is_local_model,
    score_model,
    select_model,
)


# ──────────────────────────────────────────────
# Stream parser edge cases
# ──────────────────────────────────────────────


class FakeSSEResponse:
    """Fake HTTP response that yields SSE lines."""

    def __init__(self, lines: list[str]) -> None:
        self.status_code = 200
        self._lines = lines

    def json(self) -> dict[str, Any]:
        return {}

    def iter_lines(self, decode_unicode: bool = True) -> Iterator[str]:
        return iter(self._lines)

    def close(self) -> None:
        pass


class TestStreamParserEdgeCases:
    """Ensure the SSE parsers handle malformed input gracefully."""

    def test_iter_sse_skips_empty_lines(self) -> None:
        from providers.openai.client import iter_sse_events

        lines: list[str] = [
            "",
            'data: {"choices": [{"delta": {"content": "hello"}}]}',
            "",
            "data: [DONE]",
        ]
        events = list(iter_sse_events(FakeSSEResponse(lines)))
        assert len(events) == 1

    def test_iter_sse_handles_whitespace_lines(self) -> None:
        from providers.openai.client import iter_sse_events

        lines = [
            "   ",
            "\n",
            'data: {"choices": [{"delta": {"content": "x"}}]}',
            "\r\n",
        ]
        events = list(iter_sse_events(FakeSSEResponse(lines)))
        assert len(events) == 1
        assert events[0]["choices"][0]["delta"]["content"] == "x"

    def test_iter_sse_ignores_malformed_json(self) -> None:
        from providers.openai.client import iter_sse_events

        lines = [
            "data: {broken json",
            'data: {"choices": [{"delta": {"content": "ok"}}]}',
            "data: [DONE]",
        ]
        events = list(iter_sse_events(FakeSSEResponse(lines)))
        assert len(events) == 1

    def test_iter_sse_rejects_non_dict_events(self) -> None:
        from providers.openai.client import iter_sse_events

        lines = ['data: "not a dict"', "data: [1, 2, 3]", "data: [DONE]"]
        events = list(iter_sse_events(FakeSSEResponse(lines)))
        assert len(events) == 0

    def test_iter_sse_stops_at_done(self) -> None:
        from providers.openai.client import iter_sse_events

        lines = [
            'data: {"choices": [{"delta": {"content": "a"}}]}',
            'data: {"choices": [{"delta": {"content": "b"}}]}',
            "data: [DONE]",
            'data: {"choices": [{"delta": {"content": "c"}}]}',
        ]
        events = list(iter_sse_events(FakeSSEResponse(lines)))
        assert len(events) == 2


# ──────────────────────────────────────────────
# Tool call integrity
# ──────────────────────────────────────────────


class TestToolCallIntegrity:
    """Ensure tool calls cannot be forged or deduplicated incorrectly."""

    def test_tool_call_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="tool call id must be non-empty"):
            ToolCall(id="", name="test", arguments={})

    def test_tool_call_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="tool call name must be non-empty"):
            ToolCall(id="abc", name="", arguments={})

    def test_tool_call_rejects_non_mapping_args(self) -> None:
        with pytest.raises(TypeError, match="tool call arguments must be a mapping"):
            ToolCall(id="abc", name="test", arguments="not a dict")  # type: ignore[arg-type]

    def test_tool_call_accepts_valid_id(self) -> None:
        call = ToolCall(id="call_123", name="test", arguments={"key": "val"})
        assert call.id == "call_123"
        assert call.name == "test"
        assert call.arguments == {"key": "val"}

    def test_assistant_tool_call_message_requires_calls(self) -> None:
        with pytest.raises(ValueError, match="at least one call"):
            AssistantToolCallMessage(tool_calls=())

    def test_tool_result_rejects_both_result_and_error(self) -> None:
        with pytest.raises(ValueError, match="both result and error"):
            ToolResultMessage(
                tool_call_id="1",
                tool_name="echo",
                result="ok",
                error="boom",
            )

    def test_tool_result_rejects_empty_id(self) -> None:
        with pytest.raises(ValueError, match="tool_call_id must be non-empty"):
            ToolResultMessage(tool_call_id="", tool_name="echo", result="ok")

    def test_tool_result_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="tool_name must be non-empty"):
            ToolResultMessage(tool_call_id="1", tool_name="", result="ok")


# ──────────────────────────────────────────────
# ChatEvent integrity
# ──────────────────────────────────────────────


class TestChatEventIntegrity:
    """ChatEvent type must be validated at construction."""

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="unsupported chat event type"):
            ChatEvent(type="unknown")

    def test_tool_call_event_requires_tool_call(self) -> None:
        with pytest.raises(ValueError, match="requires a ToolCall"):
            ChatEvent(type="tool_call")

    def test_tool_call_delta_is_valid(self) -> None:
        """tool_call_delta is a valid event type without a ToolCall."""
        evt = ChatEvent(type="tool_call_delta")
        assert evt.type == "tool_call_delta"

    def test_delta_and_done_are_valid(self) -> None:
        for t in ("delta", "done"):
            evt = ChatEvent(type=t)
            assert evt.type == t


# ──────────────────────────────────────────────
# Error redaction integrity
# ──────────────────────────────────────────────


class TestSecretRedaction:
    """Secret redaction must cover all known patterns."""

    def test_redacts_long_openai_key(self) -> None:
        result = redact_secrets("key=sk-live-AbCdEfGhIjKlMnOp")
        assert "AbCdEfGhIjKlMnOp" not in result
        assert "[REDACTED]" in result

    def test_redacts_gemini_key(self) -> None:
        result = redact_secrets("AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz")
        assert "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz" not in result
        assert "[REDACTED]" in result

    def test_redacts_bearer_token(self) -> None:
        result = redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")
        assert "[REDACTED]" in result

    def test_redacts_api_key_assignment(self) -> None:
        result = redact_secrets("api_key: abcdefgh12345678")
        assert "abcdefgh12345678" not in result

    def test_leaves_plain_text(self) -> None:
        result = redact_secrets("The user sent a message about the weather")
        assert result == "The user sent a message about the weather"

    def test_redacts_multiple_secrets(self) -> None:
        text = "sk-AbCdEfGhIjKlMn and AIzaAbCdEfGhIjKl"
        result = redact_secrets(text)
        assert result.count("[REDACTED]") >= 2


# ──────────────────────────────────────────────
# Endpoint security integrity
# ──────────────────────────────────────────────


class TestEndpointSecurity:
    """Local adapters must never connect to non-loopback hosts when restricted."""

    def test_loopback_hosts_are_allowed(self) -> None:
        assert is_loopback_host("localhost")
        assert is_loopback_host("127.0.0.1")
        assert is_loopback_host("::1")

    def test_non_loopback_is_rejected(self) -> None:
        assert not is_loopback_host("192.168.1.1")
        assert not is_loopback_host("0.0.0.0")
        assert not is_loopback_host("example.com")

    def test_assert_endpoint_allows_loopback(self) -> None:
        assert_endpoint_allowed(
            "http://127.0.0.1:8080",
            allow_remote=False,
            provider_id="local",
        )

    def test_assert_endpoint_rejects_remote_when_restricted(self) -> None:
        with pytest.raises(ProviderOfflineError, match="refusing non-loopback"):
            assert_endpoint_allowed(
                "http://192.168.1.100:8080",
                allow_remote=False,
                provider_id="local",
            )

    def test_assert_endpoint_allows_remote_when_allowed(self) -> None:
        assert_endpoint_allowed(
            "http://example.com:8080",
            allow_remote=True,
            provider_id="local",
        )

    def test_join_endpoint_preserves_base(self) -> None:
        result = join_endpoint("http://127.0.0.1:8080", "/v1/chat")
        assert result == "http://127.0.0.1:8080/v1/chat"

    def test_join_endpoint_strips_trailing_slash(self) -> None:
        result = join_endpoint("http://127.0.0.1:8080/", "/v1/chat")
        assert result == "http://127.0.0.1:8080/v1/chat"

    def test_origin_of_returns_scheme_netloc(self) -> None:
        assert origin_of("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080"

    def test_parse_endpoint_rejects_bad_url(self) -> None:
        with pytest.raises(ProviderError):
            parse_endpoint_host("")
        with pytest.raises(ProviderError):
            parse_endpoint_host("not-a-url")
        with pytest.raises(ProviderError):
            parse_endpoint_host("ftp://127.0.0.1")

    def test_is_loopback_url_on_invalid(self) -> None:
        assert not is_loopback_url("not-a-url")


# ──────────────────────────────────────────────
# Capabilities integrity
# ──────────────────────────────────────────────


class TestCapabilitiesIntegrity:
    """Capability checks must never allow mismatched role/capability combos."""

    def test_all_role_map_entries_have_flag(self) -> None:
        for role, flag in ROLE_CAPABILITY_FLAGS.items():
            assert hasattr(ModelInfo, flag), f"{flag} missing from ModelInfo"

    def test_all_known_roles_in_model_role_keys(self) -> None:
        for role in KNOWN_ROLES:
            assert role in ROLE_CAPABILITY_FLAGS, f"{role} missing from ROLE_CAPABILITY_FLAGS"

    def test_unregistered_role_fails_supports(self) -> None:
        model = ModelInfo(
            provider_id="test",
            model_id="m1",
            display_name="m1",
            text=True,
            streaming=True,
            local=True,
        )
        assert not supports(model, "nonexistent_role")

    def test_require_capability_raises_on_mismatch(self) -> None:
        model = ModelInfo(
            provider_id="test",
            model_id="m1",
            display_name="m1",
            text=True,
            streaming=True,
            local=True,
        )
        with pytest.raises(CapabilityError):
            require_capability(model, "vision")

    def test_require_provider_match_blocks_cross_provider(self) -> None:
        model = ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.0",
            display_name="Gemini",
            text=True,
            streaming=True,
            local=True,
        )
        with pytest.raises(CapabilityError, match="does not match"):
            require_provider_match(model, "openai")

    def test_require_capabilities_unknown_flags_fail(self) -> None:
        model = ModelInfo(
            provider_id="test",
            model_id="m1",
            display_name="m1",
            text=True,
            streaming=True,
            local=True,
        )
        with pytest.raises(CapabilityError):
            require_capabilities(model, ["unknown_cap"])


# ──────────────────────────────────────────────
# Registry integrity
# ──────────────────────────────────────────────


class TestRegistryIntegrity:
    """Registry must maintain state consistency."""

    def setup_method(self) -> None:
        clear()

    def teardown_method(self) -> None:
        clear()

    def test_thread_safe_concurrent_register(self) -> None:
        """Multiple threads can register without corrupting state."""
        errors: list[BaseException] = []

        def register_batch(prefix: str, count: int) -> None:
            try:
                for i in range(count):
                    register(f"{prefix}_{i}", lambda: None)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_batch, args=("a", 50)),
            threading.Thread(target=register_batch, args=("b", 50)),
            threading.Thread(target=register_batch, args=("c", 50)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"thread errors: {errors}"
        ids = registered_ids()
        assert len(ids) == 150

    def test_thread_safe_concurrent_read_while_register(self) -> None:
        """Reading while registering does not raise."""
        stop = threading.Event()

        def register_loop() -> None:
            i = 0
            while not stop.is_set():
                register(f"dynamic_{i}", lambda: None)
                i += 1

        def read_loop() -> None:
            while not stop.is_set():
                _ = registered_ids()
                _ = get("a") if "a" in registered_ids() else None

        t1 = threading.Thread(target=register_loop)
        t2 = threading.Thread(target=read_loop)
        t1.start()
        t2.start()
        time.sleep(0.3)
        stop.set()
        t1.join(timeout=2)
        t2.join(timeout=2)

    def test_clear_is_idempotent(self) -> None:
        register("a", lambda: None)
        clear()
        clear()
        assert registered_ids() == ()

    def test_registered_ids_are_deterministic(self) -> None:
        register("z", lambda: None)
        register("a", lambda: None)
        ids = registered_ids()
        assert ids == ("a", "z")


# ──────────────────────────────────────────────
# Router cache integrity
# ──────────────────────────────────────────────


class TestRouterCacheIntegrity:
    """Router._resolved cache must be consistent."""

    def test_cache_reuses_same_instance(self) -> None:
        mock1 = MagicMock()
        mock1.validate = MagicMock(
            return_value=ProviderStatus(provider_id="test", ok=True)
        )

        router = Router(
            provider_id="test",
            providers={"test": mock1},
            models=(
                ModelInfo(
                    provider_id="test",
                    model_id="m1",
                    display_name="m1",
                    text=True,
                    streaming=True,
                    local=True,
                ),
            ),
        )
        r1 = router._resolve("test")
        r2 = router._resolve("test")
        assert r1 is r2

    def test_injected_not_overwritten(self) -> None:
        mock1 = MagicMock()
        mock1.validate = MagicMock(
            return_value=ProviderStatus(provider_id="test", ok=True)
        )
        mock2 = MagicMock()
        mock2.validate = MagicMock(
            return_value=ProviderStatus(provider_id="test", ok=True)
        )

        router = Router(
            provider_id="test",
            providers={"test": mock1},
            models=(
                ModelInfo(
                    provider_id="test",
                    model_id="m1",
                    display_name="m1",
                    text=True,
                    streaming=True,
                    local=True,
                ),
            ),
        )
        r1 = router._resolve("test")
        assert r1 is mock1


# ──────────────────────────────────────────────
# Routing integrity
# ──────────────────────────────────────────────


class TestRoutingIntegrity:
    """Routing mode must never silently accept invalid configurations."""

    def test_routing_modes_are_closed_set(self) -> None:
        assert "manual" in ROUTING_MODES
        assert "local_first" in ROUTING_MODES
        assert "local_only" in ROUTING_MODES
        assert "cloud_first" in ROUTING_MODES

    def test_cloud_ids_are_not_local(self) -> None:
        for pid in CLOUD_PROVIDER_IDS:
            assert pid not in LOCAL_PROVIDER_IDS

    def test_local_ids_are_not_cloud(self) -> None:
        for pid in LOCAL_PROVIDER_IDS:
            assert pid not in CLOUD_PROVIDER_IDS

    def test_select_model_rejects_unknown_mode(self) -> None:
        models = [
            ModelInfo(
                provider_id="local",
                model_id="gguf",
                display_name="gguf",
                text=True,
                streaming=True,
                tool_calling=True,
                local=True,
            ),
        ]
        with pytest.raises(ProviderError, match="unknown routing mode"):
            select_model(
                models,
                routing_mode="invalid_mode",
                configured_provider_id="local",
            )

    def test_score_model_rejects_incapable_model(self) -> None:
        model = ModelInfo(
            provider_id="local",
            model_id="gguf",
            display_name="gguf",
            text=False,
            streaming=True,
            local=True,
        )
        with pytest.raises(CapabilityError):
            score_model(
                model,
                required_capabilities=frozenset({"text"}),
                prefer_local=True,
                privacy_profile="hybrid",
                availability=True,
            )

    def test_score_model_rejects_unavailable_model(self) -> None:
        model = ModelInfo(
            provider_id="local",
            model_id="gguf",
            display_name="gguf",
            text=True,
            streaming=True,
            local=True,
        )
        with pytest.raises(CapabilityError):
            score_model(
                model,
                required_capabilities=frozenset({"text"}),
                prefer_local=True,
                privacy_profile="hybrid",
                availability=False,
            )

    def test_score_model_rejects_privacy_violation(self) -> None:
        model = ModelInfo(
            provider_id="openai",
            model_id="gpt-4",
            display_name="GPT-4",
            text=True,
            streaming=True,
            tool_calling=True,
            local=False,
        )
        with pytest.raises(CapabilityError):
            score_model(
                model,
                required_capabilities=frozenset({"text"}),
                prefer_local=True,
                privacy_profile="fully_local",
                availability=True,
            )

    def test_select_model_empty_permitted_raises(self) -> None:
        models = [
            ModelInfo(
                provider_id="openai",
                model_id="gpt-4",
                display_name="GPT-4",
                text=True,
                streaming=True,
                tool_calling=True,
                local=False,
            ),
        ]
        with pytest.raises(CapabilityError, match="no model satisfies"):
            select_model(
                models,
                routing_mode="local_only",
                configured_provider_id="openai",
            )


# ──────────────────────────────────────────────
# Contract integrity
# ──────────────────────────────────────────────


class TestContractIntegrity:
    """Conversation messages must always be internally consistent."""

    def test_chat_message_defaults(self) -> None:
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_calls == ()
        assert msg.tool_call_id is None
        assert msg.name is None
        assert msg.result is None
        assert msg.error is None
        assert msg.artifacts == ()

    def test_user_message_role_fixed(self) -> None:
        msg = UserMessage(content="hello")
        assert msg.role == "user"

    def test_system_message_role_fixed(self) -> None:
        msg = SystemMessage(content="be helpful")
        assert msg.role == "system"

    def test_assistant_message_defaults(self) -> None:
        msg = AssistantMessage(content="hello")
        assert msg.role == "assistant"
        assert msg.tool_calls == ()

    def test_tool_result_message_defaults(self) -> None:
        msg = ToolResultMessage(tool_call_id="1", tool_name="echo", result="ok")
        assert msg.role == "tool"
        assert msg.content == ""
        assert msg.artifacts == ()
        assert msg.name == "echo"

    def test_conversation_message_type_is_union(self) -> None:
        messages: list[ConversationMessage] = [
            UserMessage(content="hi"),
            SystemMessage(content="be helpful"),
            AssistantMessage(content="hello"),
            AssistantToolCallMessage(
                tool_calls=(ToolCall(id="1", name="t", arguments={}),)
            ),
            ToolResultMessage(tool_call_id="1", tool_name="t", result="ok"),
            ChatMessage(role="user", content="hi"),
        ]
        assert len(messages) == 6


# ──────────────────────────────────────────────
# Local endpoint validation integrity
# ──────────────────────────────────────────────


class TestLocalEndpointValidation:
    """Local providers must validate endpoints before any I/O."""

    @pytest.mark.asyncio
    async def test_local_provider_rejects_remote_when_not_allowed(self) -> None:
        with pytest.raises(ProviderOfflineError, match="refusing non-loopback"):
            from providers.local.openai_compatible import OpenAICompatibleChatProvider

            OpenAICompatibleChatProvider(
                base_url="http://192.168.1.100:8080/v1",
            )

    @pytest.mark.asyncio
    async def test_local_provider_allows_loopback(self) -> None:
        from providers.local.http import TransportResponse
        from providers.local.openai_compatible import OpenAICompatibleChatProvider

        fake_transport = MagicMock()
        fake_transport.request.return_value = TransportResponse(
            status_code=200, body='{"data": []}', headers={}
        )

        provider = OpenAICompatibleChatProvider(
            base_url="http://127.0.0.1:8080/v1",
            transport=fake_transport,
        )
        status = await provider.validate()
        assert status.ok is True

    @pytest.mark.asyncio
    async def test_local_provider_chat_rejects_remote_at_runtime(self) -> None:
        """The loopback guard is re-evaluated on every _request call,
        so even if allow_remote was True at construction, changing it
        later still blocks."""
        from providers.local.http import TransportResponse, StdlibTransport
        from providers.local.openai_compatible import OpenAICompatibleChatProvider

        fake_transport = MagicMock(spec=StdlibTransport)
        fake_transport.request.return_value = TransportResponse(
            status_code=200, body='{"data": []}', headers={}
        )

        # allow_remote=True to pass __init__
        provider = OpenAICompatibleChatProvider(
            base_url="http://192.168.1.100:8080/v1",
            allow_remote=True,
            transport=fake_transport,
        )
        # Set it back to False to simulate runtime restriction
        provider.allow_remote = False
        model = ModelInfo(
            provider_id="local",
            model_id="m1",
            display_name="m1",
            text=True,
            streaming=True,
            tool_calling=True,
            local=True,
        )
        request = ChatRequest(model=model, messages=[UserMessage(content="hi")])
        # The _request method re-checks the endpoint every time
        with pytest.raises(ProviderOfflineError, match="refusing non-loopback"):
            await provider.chat(request)


# ──────────────────────────────────────────────
# Missing __all__ exports
# ──────────────────────────────────────────────


class TestModuleExports:
    """All public provider modules should have __all__ defined."""

    def test_errors_module_has_all(self) -> None:
        import providers.errors as mod

        assert hasattr(mod, "__all__"), "providers.errors should define __all__"

    def test_registry_module_has_all(self) -> None:
        import providers.registry as mod

        assert hasattr(mod, "__all__"), "providers.registry should define __all__"

    def test_capabilities_module_has_all(self) -> None:
        import providers.capabilities as mod

        assert hasattr(mod, "__all__"), "providers.capabilities should define __all__"

    def test_openai_provider_has_provider_id(self) -> None:
        """provider_id is set on the instance, verify it works."""
        from providers.openai.provider import PROVIDER_ID as MOD_ID

        provider = OpenAIChatProvider(api_key="test")
        assert hasattr(provider, "provider_id")
        assert provider.provider_id == MOD_ID
