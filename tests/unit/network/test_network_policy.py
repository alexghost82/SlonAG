"""Unit tests for NetworkPolicy modes, cloud gate, and proxy guard."""

from __future__ import annotations

import mark.network.hosts as hosts_mod
import pytest

from mark.network import (
    CODE_OFFLINE,
    CODE_OK,
    CODE_PROXY_FORCED_EXTERNAL,
    CODE_TOOL_NOT_ALLOWED,
    CODE_UNSAFE_HOST,
    NetworkDeniedError,
    NetworkMode,
    NetworkPolicy,
)

SECRET = "sk-abcdefghijklmnopqrstuvwxyz012345"


def test_offline_denies_example_com() -> None:
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE)
    decision = policy.check_request(url="https://example.com")
    assert decision.allowed is False
    assert decision.reason == CODE_OFFLINE
    assert decision.domain == "example.com"


def test_offline_allows_loopback_local_runtime() -> None:
    policy = NetworkPolicy(mode="offline")
    decision = policy.check_request(url="http://127.0.0.1:11434")
    assert decision.allowed is True
    assert decision.reason == CODE_OK
    assert decision.domain == "127.0.0.1"


@pytest.mark.parametrize(
    "url",
    (
        "http://localhost:11434/api/tags",
        "http://[::1]:8080/",
        "http://127.0.0.1/",
    ),
)
def test_offline_allows_loopback_names(url: str) -> None:
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE)
    assert policy.check_request(url=url).allowed is True


def test_tools_only_requires_allowlist() -> None:
    policy = NetworkPolicy(
        mode=NetworkMode.TOOLS_ONLY,
        tool_allowlist=frozenset({"web_search"}),
    )
    denied = policy.check_request(url="https://example.com", tool="browser")
    assert denied.allowed is False
    assert denied.reason == CODE_TOOL_NOT_ALLOWED

    allowed = policy.check_request(url="https://example.com", tool="web_search")
    assert allowed.allowed is True
    assert allowed.reason == CODE_OK


def test_tools_only_still_allows_loopback_without_tool() -> None:
    policy = NetworkPolicy(mode=NetworkMode.TOOLS_ONLY, tool_allowlist=frozenset())
    decision = policy.check_request(url="http://127.0.0.1:11434")
    assert decision.allowed is True


def test_hybrid_allows_public_https() -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID)
    decision = policy.check_request(url="https://example.com/path")
    assert decision.allowed is True
    assert decision.reason == CODE_OK


def test_hybrid_denies_metadata() -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID)
    decision = policy.check_request(url="http://169.254.169.254/latest/meta-data")
    assert decision.allowed is False
    assert decision.reason == CODE_UNSAFE_HOST


@pytest.mark.parametrize(
    "url",
    (
        "http://metadata.google.internal/",
        "http://169.254.1.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
    ),
)
def test_hybrid_denies_unsafe_hosts_by_default(url: str) -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID)
    assert policy.check_request(url=url).reason == CODE_UNSAFE_HOST


def test_hybrid_can_allow_private_lan_when_enabled() -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID, allow_private_lan=True)
    decision = policy.check_request(url="http://10.0.0.5:8080/")
    assert decision.allowed is True
    # Metadata stays blocked even with LAN enabled.
    meta = policy.check_request(url="http://169.254.169.254/")
    assert meta.allowed is False


def test_allows_cloud_provider_false_offline() -> None:
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE)
    for provider_id in ("gemini", "openai", "openrouter"):
        assert policy.allows_cloud_provider(provider_id) is False


def test_allows_cloud_provider_false_fully_local_privacy() -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID, privacy_profile="fully_local")
    assert policy.allows_cloud_provider("openai") is False
    assert policy.allows_cloud_provider("gemini") is False


def test_allows_cloud_provider_true_hybrid() -> None:
    policy = NetworkPolicy(mode=NetworkMode.HYBRID, privacy_profile="hybrid")
    assert policy.allows_cloud_provider("openrouter") is True
    assert policy.allows_cloud_provider("local") is False


def test_proxy_cannot_turn_loopback_external() -> None:
    policy = NetworkPolicy(
        mode=NetworkMode.OFFLINE,
        environ={
            "HTTP_PROXY": "http://proxy.example.com:8080",
            "HTTPS_PROXY": "http://proxy.example.com:8080",
            "ALL_PROXY": "socks5://proxy.example.com:1080",
        },
    )
    decision = policy.check_request(url="http://127.0.0.1:11434")
    assert decision.allowed is False
    assert decision.reason == CODE_PROXY_FORCED_EXTERNAL


def test_loopback_proxy_does_not_block_loopback_target() -> None:
    policy = NetworkPolicy(
        mode=NetworkMode.OFFLINE,
        environ={"HTTP_PROXY": "http://127.0.0.1:8899"},
    )
    decision = policy.check_request(url="http://127.0.0.1:11434")
    assert decision.allowed is True


def test_require_request_raises_secret_free_error() -> None:
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE)
    with pytest.raises(NetworkDeniedError) as exc_info:
        policy.require_request(url=f"https://example.com/?api_key={SECRET}")
    assert exc_info.value.code == CODE_OFFLINE
    assert SECRET not in str(exc_info.value)
    assert "example.com" not in str(exc_info.value)


def test_hosts_module_does_not_import_socket() -> None:
    assert "socket" not in hosts_mod.__dict__
    assert "request" not in hosts_mod.__dict__


def test_does_not_mutate_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    injected = {"HTTP_PROXY": "http://evil.example:1"}
    policy = NetworkPolicy(mode=NetworkMode.HYBRID, environ=injected)
    policy.check_request(url="http://127.0.0.1:1")
    assert "HTTP_PROXY" not in __import__("os").environ
