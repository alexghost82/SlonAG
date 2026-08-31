"""Tests for mark/connectivity/transport.py — TLS/WSS transport layer."""

from __future__ import annotations

import asyncio
import ssl
from unittest.mock import MagicMock, patch

import pytest

from mark.connectivity.transport import (
    LANTransport,
    LANTransportError,
    MAX_MESSAGE_BYTES,
    TransportConfig,
    _encode_text_frame,
    _decode_text_frame,
)


class TestTransportConfig:
    def test_defaults(self) -> None:
        config = TransportConfig(host="192.168.1.42", port=8765)
        assert config.url == "wss://192.168.1.42:8765"
        assert config.verify_certificate is True
        assert config.heartbeat_interval == 15.0
        assert config.heartbeat_timeout == 45.0
        assert config.scheme == "wss"

    def test_from_lan_device(self, fake_lan_device) -> None:
        config = TransportConfig.from_lan_device(fake_lan_device)
        assert config.host == "192.168.1.42"
        assert config.port == 8765
        assert config.certificate_fingerprint == "a1b2c3d4e5f67890"
        assert config.verify_certificate is True

    def test_custom_scheme(self) -> None:
        config = TransportConfig(host="1.2.3.4", port=80, scheme="ws")
        assert config.url == "ws://1.2.3.4:80"


class TestLANTransport:
    def test_closed_raises_send(self) -> None:
        transport = LANTransport(TransportConfig(host="1.2.3.4", port=80))
        transport._closed = True
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(LANTransportError, match="connected"):
                loop.run_until_complete(transport.send("test", {}))
        finally:
            loop.close()

    def test_not_connected_raises_send(self) -> None:
        transport = LANTransport(TransportConfig(host="1.2.3.4", port=80))
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(LANTransportError, match="Not connected"):
                loop.run_until_complete(transport.send("test", {}))
        finally:
            loop.close()

    def test_connected_property(self) -> None:
        transport = LANTransport(TransportConfig(host="1.2.3.4", port=80))
        assert transport.connected is False

    def test_stale_before_connect(self) -> None:
        transport = LANTransport(TransportConfig(host="1.2.3.4", port=80))
        assert transport.is_stale() is True

    def test_stale_after_connect(self) -> None:
        transport = LANTransport(TransportConfig(host="1.2.3.4", port=80))
        transport._connected = True
        assert transport.is_stale() is False
        transport._last_pong_at = 0.0
        assert transport.is_stale(max_age=1.0) is True

    def test_close_no_ws(self) -> None:
        transport = LANTransport(TransportConfig(host="1.2.3.4", port=80))
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(transport.close())
        finally:
            loop.close()
