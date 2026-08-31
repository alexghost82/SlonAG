"""Tests for mark/connectivity/migration.py — LAN/remote migration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mark.connectivity.migration import LANRemoteMigration
from mark.connectivity.types import ConnectionState, TransportKind


class TestLANRemoteMigration:
    def test_init(self) -> None:
        session = MagicMock()
        migration = LANRemoteMigration(session)
        assert migration._session is session

    def test_find_best_lan_device_returns_none(self) -> None:
        session = MagicMock()
        migration = LANRemoteMigration(session)

        mock_scanner = MagicMock()
        mock_scanner.scan_once = MagicMock(return_value=[])
        with patch("mark.connectivity.discovery.LANDeviceScanner", return_value=mock_scanner):
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(migration.find_best_lan_device())
            finally:
                loop.close()
            assert result is None

    def test_reauthenticate_remote_no_adapter(self) -> None:
        session = MagicMock()
        session._remote_adapter = None
        migration = LANRemoteMigration(session)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(migration._reauthenticate_remote())
        finally:
            loop.close()


class TestMigrationNotify:
    def test_notify_migration(self) -> None:
        session = MagicMock()
        migration = LANRemoteMigration(session)
        migration._notify_migration(
            MagicMock(from_kind=TransportKind.LAN_TLS, to_kind=TransportKind.REMOTE)
        )
        session._notify_state.assert_called_once()


class TestMigrationToRemote:
    def test_migration_to_remote(self) -> None:
        session = MagicMock()
        session.current_transport = TransportKind.LAN_TLS
        session._transport = MagicMock()
        session._transport.close = AsyncMock()
        session._remote_adapter = None
        session.info.return_value.session_id = "sess-123"

        migration = LANRemoteMigration(session)

        mock_adapter = AsyncMock()
        mock_adapter.connect = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        with patch("mark.connectivity.remote.RemoteAdapter", return_value=mock_adapter):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(migration.migrate_to_remote(reason="test"))
            finally:
                loop.close()

        assert session.state == ConnectionState.CONNECTED
        assert session.current_transport == TransportKind.REMOTE


class TestMigrationToLan:
    def test_migration_to_lan(self) -> None:
        session = MagicMock()
        session.current_transport = TransportKind.REMOTE
        session._remote_adapter = MagicMock()
        session._remote_adapter.disconnect = AsyncMock()
        session.info.return_value.session_id = "sess-123"

        device = MagicMock()
        device.host = "192.168.1.1"
        device.port = 8765
        device.uses_tls = True

        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        with patch("mark.connectivity.transport.LANTransport", return_value=mock_transport):
            migration = LANRemoteMigration(session)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(migration.migrate_to_lan(device, reason="lan_restored"))
            finally:
                loop.close()

        assert session.state == ConnectionState.CONNECTED
        assert session.current_transport == TransportKind.LAN_TLS
