"""Tests for acta/connectivity/types.py — core type definitions."""

from __future__ import annotations

import platform
import time

import pytest

from acta.connectivity.types import (
    ConnectivityMode,
    ConnectivityPolicy,
    ConnectionConnectionReason,
    ConnectionInfo,
    ConnectionState,
    ConnectionReason,
    DeviceIdentity,
    DiscoveredDevice,
    MigrationEvent,
    TransportEndpoint,
    TransportKind,
    TransportMessage,
    TransportSession,
)


class TestTransportKind:
    def test_transport_kind_values(self) -> None:
        assert TransportKind.LAN_TLS == "lan_tls"
        assert TransportKind.LAN_WS == "lan_ws"
        assert TransportKind.REMOTE == "remote"
        assert TransportKind.LOCAL == "local"


class TestConnectivityMode:
    def test_mode_values(self) -> None:
        assert ConnectivityMode.AUTO == "auto"
        assert ConnectivityMode.LAN_ONLY == "lan_only"
        assert ConnectivityMode.REMOTE_ONLY == "remote_only"


class TestConnectionState:
    def test_state_progression(self) -> None:
        assert ConnectionState.DISCONNECTED == "disconnected"
        assert ConnectionState.CONNECTING == "connecting"
        assert ConnectionState.CONNECTED == "connected"
        assert ConnectionState.MIGRATING == "migrating"
        assert ConnectionState.ERROR == "error"


class TestConnectionReason:
    def test_reason_values(self) -> None:
        assert ConnectionReason.MANUAL_DISCONNECT == "manual_disconnect"
        assert ConnectionReason.LAN_AVAILABLE == "lan_available"
        assert ConnectionReason.LAN_LOST == "lan_lost"
        assert ConnectionReason.HEARTBEAT_TIMEOUT == "heartbeat_timeout"
        assert ConnectionReason.CERTIFICATE_ERROR == "certificate_error"
        assert ConnectionReason.AUTH_FAILED == "auth_failed"


class TestDeviceIdentity:
    def test_generate(self) -> None:
        identity = DeviceIdentity.generate("My Desktop")
        assert identity.device_id.startswith("dev-")
        assert len(identity.display_name) > 0
        assert identity.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert len(identity.fingerprint_sha256) == 16
        assert isinstance(identity.created_at, float)

    def test_generate_with_kwargs(self) -> None:
        identity = DeviceIdentity.generate("Test", model="MacBook Pro", os_name="Darwin")
        assert identity.model == "MacBook Pro"
        # os_name from kwargs should override platform.system()
        assert identity.os_name == "Darwin"

    def test_os_name_defaults_to_platform(self) -> None:
        identity = DeviceIdentity.generate("Test")
        assert identity.os_name == platform.system()

    def test_is_frozen(self) -> None:
        identity = DeviceIdentity.generate("Test")
        with pytest.raises(Exception):  # frozen dataclass
            identity.device_id = "new"


class TestDiscoveredDevice:
    def test_defaults(self) -> None:
        device = DiscoveredDevice(
            host="192.168.1.1",
            port=8765,
            device_id="dev-abc",
            display_name="Test",
            fingerprint="abcdef",
        )
        assert device.service_type == "_mark-control._tcp.local."
        assert isinstance(device.discovered_at, float)

    def test_timestamp_auto_set(self) -> None:
        before = time.time()
        device = DiscoveredDevice(
            host="10.0.0.1",
            port=8765,
            device_id="dev-xyz",
            display_name="Test",
            fingerprint="xyz123",
        )
        after = time.time()
        assert before <= device.discovered_at <= after

    def test_properties_empty_by_default(self) -> None:
        device = DiscoveredDevice(
            host="1.2.3.4",
            port=80,
            device_id="id",
            display_name="n",
            fingerprint="f",
        )
        assert device.properties == {}


class TestTransportEndpoint:
    def test_defaults(self) -> None:
        ep = TransportEndpoint(kind=TransportKind.LAN_TLS, url="wss://192.168.1.1:8765", host="192.168.1.1", port=8765)
        assert ep.device_id == ""
        assert ep.verify_certificate is True


class TestTransportSession:
    def test_defaults(self) -> None:
        ep = TransportEndpoint(kind=TransportKind.LAN_TLS, url="wss://x:80", host="x", port=80)
        session = TransportSession(endpoint=ep)
        assert len(session.session_id) == 32  # hex uuid


class TestTransportMessage:
    def test_defaults(self) -> None:
        msg = TransportMessage()
        assert msg.kind == ""
        assert msg.payload == {}
        assert msg.sequence == 0
        assert isinstance(msg.timestamp, float)


class TestConnectionInfo:
    def test_defaults(self) -> None:
        info = ConnectionInfo(
            device_id="dev-test",
            transport_kind=TransportKind.LAN_TLS,
            state=ConnectionState.CONNECTED,
        )
        assert info.reason == ""
        assert info.established_at == 0.0
        assert info.heartbeat_interval == 15.0
        assert info.heartbeat_timeout == 45.0


class TestMigrationEvent:
    def test_defaults(self) -> None:
        ev = MigrationEvent(
            from_kind=TransportKind.LAN_TLS,
            to_kind=TransportKind.REMOTE,
            reason="test_migration",
            session_id="sess-123",
        )
        assert isinstance(ev.timestamp, float)


class TestConnectivityPolicy:
    def test_defaults(self) -> None:
        p = ConnectivityPolicy()
        assert p.preferred_mode == ConnectivityMode.AUTO
        assert p.lan_preferred is True
        assert p.remote_fallback is True
        assert p.auto_reconnect is True
        assert p.certificate_verify is True
        assert p.prefer_secure is True


class TestBackwardCompatAlias:
    def test_connection_connection_reason(self) -> None:
        """ConnectionConnectionReason should be an alias for ConnectionReason."""
        assert ConnectionConnectionReason.LAN_AVAILABLE == ConnectionReason.LAN_AVAILABLE
        assert ConnectionConnectionReason.MANUAL_DISCONNECT == ConnectionReason.MANUAL_DISCONNECT
