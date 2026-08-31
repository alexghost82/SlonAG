"""Shared fixtures for connectivity tests."""

from __future__ import annotations

import pytest


@pytest.fixture()
def fake_lan_device():
    """Create a fake LAN device for tests."""
    from mark.connectivity.discovery import LANDevice
    return LANDevice(
        name="Slon Desktop._mark-control._tcp.local.",
        host="192.168.1.42",
        port=8765,
        device_id="dev-test-fake-001",
        display_name="Desktop Control",
        fingerprint="a1b2c3d4e5f67890",
        uses_tls=True,
    )


@pytest.fixture()
def fake_policy():
    """Create a default ConnectivityPolicy for tests."""
    from mark.connectivity.types import ConnectivityPolicy
    return ConnectivityPolicy(
        lan_preferred=True,
        remote_fallback=True,
        auto_reconnect=True,
        heartbeat_interval=1.0,  # fast for tests
        heartbeat_timeout=2.0,  # fast for tests
        max_reconnect_attempts=3,
        lan_reconnect_delay=0.1,  # fast for tests
    )
