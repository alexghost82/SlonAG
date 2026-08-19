"""Offline scenario: local failure must not unlock cloud providers."""

from __future__ import annotations

from mark.network import NetworkMode, NetworkPolicy

CLOUD_IDS = ("gemini", "openai", "openrouter")


def test_local_failure_still_denies_cloud_in_offline_mode() -> None:
    """Simulate local runtime failed → would fall back to cloud.

    NetworkPolicy(mode=offline) must still deny gemini/openai/openrouter.
    No live HTTP is performed.
    """
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE, privacy_profile="hybrid")

    local_failed = True
    assert local_failed is True

    # A caller that would normally choose cloud after local failure.
    fallback_provider = "openai" if local_failed else "local"

    assert policy.allows_cloud_provider(fallback_provider) is False
    for provider_id in CLOUD_IDS:
        assert policy.allows_cloud_provider(provider_id) is False

    # External cloud endpoints remain denied even after the local failure flag.
    denied = policy.check_request(
        url="https://generativelanguage.googleapis.com/v1",
        tool="chat",
        purpose="cloud_fallback_after_local_failure",
    )
    assert denied.allowed is False
    assert denied.reason == "offline"

    # Loopback local runtime stays reachable for a retry without leaving the host.
    local_retry = policy.check_request(url="http://127.0.0.1:11434/api/tags")
    assert local_retry.allowed is True
