"""Tests for mark/connectivity/monitor.py — connection health monitoring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mark.connectivity.monitor import ConnectivityMonitor
from mark.connectivity.types import ConnectionState, TransportKind


class TestConnectivityMonitor:
    def test_initial_state(self) -> None:
        session = MagicMock()
        monitor = ConnectivityMonitor(session)
        assert monitor._task is None
        assert monitor._last_pong_at > 0

    def test_last_pong_at_property(self) -> None:
        session = MagicMock()
        monitor = ConnectivityMonitor(session)
        assert monitor._last_pong_at > 0

    def test_ping_no_transport(self) -> None:
        session = MagicMock()
        session._transport = None
        session._remote_adapter = None
        monitor = ConnectivityMonitor(session)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(monitor.ping())
        finally:
            loop.close()
        assert result is False

    def test_ping_lan_transport(self) -> None:
        session = MagicMock()
        transport = MagicMock()
        transport.connected = True
        transport.ping = AsyncMock(return_value=True)
        session._transport = transport
        session._remote_adapter = None
        monitor = ConnectivityMonitor(session)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(monitor.ping())
        finally:
            loop.close()
        assert result is True

    def test_stale_before_connect(self) -> None:
        session = MagicMock()
        monitor = ConnectivityMonitor(session)
        assert monitor.is_stale() is True

    def test_not_stale(self) -> None:
        session = MagicMock()
        monitor = ConnectivityMonitor(session)
        monitor._connected = True
        assert monitor.is_stale(max_age=99999) is False

    def test_start_stops_cleanly(self) -> None:
        session = MagicMock()
        monitor = ConnectivityMonitor(session)
        monitor._stop.set()  # prevent actual monitoring loop from running
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(monitor.start())
            loop.run_until_complete(monitor.stop())
        finally:
            loop.close()

    def test_stop_cleanly(self) -> None:
        session = MagicMock()
        monitor = ConnectivityMonitor(session)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(monitor.stop())
        finally:
            loop.close()


import asyncio
