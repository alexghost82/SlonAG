"""Tests for mark/connectivity/session.py — session state machine."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mark.connectivity.session import ConnectivitySession, ConnectivitySessionError
from mark.connectivity.types import (
    ConnectionConnectionReason,
    ConnectionInfo,
    ConnectionState,
    ConnectionReason,
    ConnectivityPolicy,
    ConnectivityMode,
    TransportKind,
)


class TestSessionInitialState:
    def test_initial_state(self) -> None:
        session = ConnectivitySession()
        assert session.state == ConnectionState.DISCONNECTED
        assert session.current_transport == TransportKind.LOCAL
        assert session.current_device is None

    def test_default_policy(self) -> None:
        session = ConnectivitySession()
        assert session.policy is not None
        assert session.policy.remote_fallback is True


class TestSessionDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect(self, fake_lan_device) -> None:
        session = ConnectivitySession()
        session.state = ConnectionState.CONNECTED
        session.current_transport = TransportKind.LAN_TLS
        session.current_device = fake_lan_device
        await session.disconnect()
        assert session.state == ConnectionState.DISCONNECTED
        assert session.current_transport == TransportKind.LOCAL
        assert session.current_device is None


class TestSessionInfo:
    def test_info_disconnected(self) -> None:
        session = ConnectivitySession()
        info = session.info()
        assert info.state == ConnectionState.DISCONNECTED
        assert info.device_id == ""
        assert info.transport_kind == TransportKind.LOCAL

    def test_info_connected(self, fake_lan_device) -> None:
        session = ConnectivitySession()
        session.state = ConnectionState.CONNECTED
        session.current_transport = TransportKind.LAN_TLS
        session.current_device = fake_lan_device
        info = session.info()
        assert info.state == ConnectionState.CONNECTED
        assert info.device_id == "dev-test-fake-001"
        assert info.transport_kind == TransportKind.LAN_TLS
        assert info.heartbeat_interval == 15.0


class TestSessionSendReceive:
    @pytest.mark.asyncio
    async def test_send_no_transport(self) -> None:
        session = ConnectivitySession()
        with pytest.raises(ConnectivitySessionError, match="No active transport"):
            await session.send("test", {})

    @pytest.mark.asyncio
    async def test_receive_no_transport(self) -> None:
        session = ConnectivitySession()
        result = await session.receive()
        assert result is None


class TestSessionCallbacks:
    def test_on_state_change(self) -> None:
        session = ConnectivitySession()
        handler = MagicMock()
        session.on_state_change(handler)
        session._notify_state()
        handler.assert_called_once()


class TestConnectionConnectionReasonAlias:
    def test_alias(self) -> None:
        """Backward compat: ConnectionConnectionReason == ConnectionReason."""
        assert ConnectionConnectionReason.LAN_AVAILABLE == "lan_available"


class TestSessionConnectNoDevices:
    @pytest.mark.asyncio
    async def test_connect_no_devices_no_remote(self) -> None:
        session = ConnectivitySession(
            policy=ConnectivityPolicy(
                preferred_mode=ConnectivityMode.LAN_ONLY,
                remote_fallback=False,
            )
        )
        with patch.object(session, "_scan_devices", return_value=[]):
            with pytest.raises(ConnectivitySessionError):
                await session.connect()


class TestSessionConnectRemote:
    @pytest.mark.asyncio
    async def test_connect_remote_fallback(self) -> None:
        session = ConnectivitySession()
        with patch.object(session, "_scan_devices", return_value=[]):
            with patch.object(session, "_connect_remote", new=AsyncMock()):
                await session.connect()
                session._connect_remote.assert_awaited_once()


class TestSessionReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_no_device(self) -> None:
        session = ConnectivitySession()
        with patch.object(session, "_scan_devices", return_value=[]):
            with pytest.raises(ConnectivitySessionError):
                await session.reconnect()


class TestSessionReceiveStream:
    @pytest.mark.asyncio
    async def test_stream_empty(self) -> None:
        session = ConnectivitySession()
        session.state = ConnectionState.DISCONNECTED
        stream = session.receive_stream()
        items = []
        async for item in stream:
            items.append(item)
        assert items == []
