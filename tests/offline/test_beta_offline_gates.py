"""Offline beta gates: NetworkPolicy + SafetyPolicy without external I/O."""

from __future__ import annotations

from mark.network import NetworkMode, NetworkPolicy
from mark.safety import UnknownToolError, UnsafeUrlError, authorize, check_url
from mark.safety.types import UntrustedSource

CLOUD_IDS = ("gemini", "openai", "openrouter")


def test_offline_network_denies_cloud_allows_loopback() -> None:
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE, privacy_profile="hybrid")
    for provider_id in CLOUD_IDS:
        assert policy.allows_cloud_provider(provider_id) is False

    external = policy.check_request(
        url="https://generativelanguage.googleapis.com/v1",
        purpose="offline_beta_gate",
    )
    assert external.allowed is False
    assert external.reason == "offline"

    local = policy.check_request(url="http://127.0.0.1:11434/api/tags")
    assert local.allowed is True


def test_offline_safety_rejects_ssrf_and_unknown_tools() -> None:
    try:
        check_url("http://metadata.google.internal/computeMetadata/v1/")
        raise AssertionError("expected UnsafeUrlError")
    except UnsafeUrlError:
        pass

    try:
        authorize(
            "not_a_real_tool",
            {"path": "/tmp"},
            source=UntrustedSource.WEB,
        )
        raise AssertionError("expected UnknownToolError")
    except UnknownToolError:
        pass
