"""Tests for mark/mcp/transport.py."""

from __future__ import annotations

import asyncio
import json
import sys
import pytest

from mark.mcp.transport import McpStdioTransport
from mark.mcp.types import McpServerConfig, McpTransportKind


class TestMcpStdioTransport:
    """Tests for the MCP stdio transport layer."""

    @pytest.mark.asyncio
    async def test_requires_command(self) -> None:
        config = McpServerConfig(name="test", transport=McpTransportKind.STDIO)
        transport = McpStdioTransport(config)
        with pytest.raises(ValueError, match="непустую команду"):
            await transport.start()

    @pytest.mark.asyncio
    async def test_starts_with_test_server(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        async with transport:
            assert transport.is_connected

    @pytest.mark.asyncio
    async def test_send_message_initialize(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        async with transport:
            result = await transport.send_message(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "slonag", "version": "0.1.0"},
                },
                timeout=5.0,
            )
            assert isinstance(result, dict)
            assert "capabilities" in result
            assert "serverInfo" in result
            assert result.get("serverInfo", {}).get("name") == "slon-test-mcp"

    @pytest.mark.asyncio
    async def test_send_message_tools_list(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        async with transport:
            await transport.send_message("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "slonag", "version": "0.1.0"},
            }, timeout=5.0)

            result = await transport.send_message("tools/list", timeout=5.0)
            assert isinstance(result, dict)
            assert "tools" in result
            tools = result["tools"]
            assert len(tools) >= 3
            names = {t.get("name") for t in tools if isinstance(t, dict)}
            assert "echo" in names
            assert "compute" in names

    @pytest.mark.asyncio
    async def test_send_message_invalid_method(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        async with transport:
            await transport.send_message("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "slonag", "version": "0.1.0"},
            }, timeout=5.0)
            with pytest.raises(RuntimeError, match="Method not found"):
                await transport.send_message("nonexistent/method", timeout=5.0)

    @pytest.mark.asyncio
    async def test_disconnect_handling(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        async with transport:
            pass  # exit context manager → transport stopped
        assert not transport.is_connected

    @pytest.mark.asyncio
    async def test_bounded_timeout(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        async with transport:
            with pytest.raises(asyncio.TimeoutError):
                await transport.send_message(
                    "tools/call",
                    {"name": "slow_operation", "arguments": {"duration_seconds": 30}},
                    timeout=0.5,
                )


class TestMcpTransportDisconnect:
    """Tests for transport handling server disconnects."""

    @pytest.mark.asyncio
    async def test_stop_twice(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        await transport.start()
        await transport.stop()
        await transport.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_send_after_stop(self) -> None:
        config = McpServerConfig(
            name="test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        transport = McpStdioTransport(config)
        await transport.start()
        await transport.stop()
        with pytest.raises(RuntimeError, match="не подключён"):
            await transport.send_message("tools/list")
