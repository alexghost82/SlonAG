"""Live / voice must fail-closed when settings forbid cloud."""

from __future__ import annotations

import pytest


def test_create_live_client_fail_closed_when_cloud_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("config.schema.settings_forbid_cloud", lambda settings=None: True)
    from providers.gemini.live import create_live_client

    with pytest.raises(RuntimeError, match="disabled"):
        create_live_client(api_key="test-key")


def test_settings_forbid_cloud_covers_required_modes() -> None:
    from config.schema import Settings, settings_forbid_cloud

    assert settings_forbid_cloud(Settings(network_mode="offline")) is True
    assert settings_forbid_cloud(Settings(routing_mode="local_only")) is True
    assert settings_forbid_cloud(Settings(privacy_profile="fully_local")) is True
    assert settings_forbid_cloud(Settings(privacy_profile="local_with_tools")) is True
    assert settings_forbid_cloud(Settings(network_mode="tools_only")) is True
    assert (
        settings_forbid_cloud(Settings(network_mode="hybrid", routing_mode="manual", privacy_profile="hybrid")) is False
    )
