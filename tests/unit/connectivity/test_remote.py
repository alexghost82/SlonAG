"""Tests for acta/connectivity/remote.py — remote transport adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from acta.connectivity.remote import RemoteAdapter, RemoteAdapterError


class TestRemoteAdapter:
    def test_default_url(self) -> None:
        adapter = RemoteAdapter()
        assert adapter.url == RemoteAdapter.DEFAULT_REMOTE_URL

    def test_custom_url(self) -> None:
        adapter = RemoteAdapter(url="wss://custom.example.com/ws")
        assert adapter.url == "wss://custom.example.com/ws"

    def test_is_relay(self) -> None:
        adapter = RemoteAdapter()
        assert adapter.is_relay() is True

    def test_connected_initially_false(self) -> None:
        adapter = RemoteAdapter()
        assert adapter.connected is False

    def test_not_connected_raises_send(self) -> None:
        adapter = RemoteAdapter()
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RemoteAdapterError, match="Not connected"):
                loop.run_until_complete(adapter.send("test", {}))
        finally:
            loop.close()

    def test_not_connected_raises_receive(self) -> None:
        adapter = RemoteAdapter()
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RemoteAdapterError, match="Not connected"):
                loop.run_until_complete(adapter.receive())
        finally:
            loop.close()

    def test_closed_raises_connect(self) -> None:
        adapter = RemoteAdapter()
        adapter._closed = True
        with pytest.raises(RemoteAdapterError, match="closed"):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(adapter.connect())
            finally:
                loop.close()

    def test_connect_calls_open(self) -> None:
        adapter = RemoteAdapter()
        mock_conn = AsyncMock()
        with patch.object(adapter, "_open_connection", new=AsyncMock(return_value=mock_conn)):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(adapter.connect())
            finally:
                loop.close()
        assert adapter.connected is True

    def test_disconnect(self) -> None:
        adapter = RemoteAdapter()
        adapter._connection = AsyncMock()
        adapter._connected = True
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(adapter.disconnect())
        finally:
            loop.close()
        assert adapter.connected is False
        assert adapter._connection is None

    def test_disconnect_no_connection(self) -> None:
        adapter = RemoteAdapter()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(adapter.disconnect())
        finally:
            loop.close()

    def test_send_increments_sequence(self) -> None:
        adapter = RemoteAdapter()
        adapter._connected = True
        mock_ws = AsyncMock()
        adapter._connection = mock_ws
        loop = asyncio.new_event_loop()
        try:
            seq = loop.run_until_complete(adapter.send("chat", {"msg": "hello"}))
        finally:
            loop.close()
        assert seq == 1

    def test_receive_timeout(self) -> None:
        adapter = RemoteAdapter()
        adapter._connected = True
        mock_ws = AsyncMock()
        mock_ws.recv.side_effect = asyncio.TimeoutError()
        adapter._connection = mock_ws
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(adapter.receive(timeout=0.1))
        finally:
            loop.close()
        assert result is None


class TestRemoteAdapterError:
    def test_default_code(self) -> None:
        err = RemoteAdapterError("test error")
        assert err.code == "remote_error"

    def test_custom_code(self) -> None:
        err = RemoteAdapterError("test", code="custom")
        assert err.code == "custom"
