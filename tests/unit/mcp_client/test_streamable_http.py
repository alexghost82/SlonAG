"""Tests for mark/mcp/streamable_http_transport.py."""

from __future__ import annotations

import pytest

from mark.mcp.client import McpClient
from mark.mcp.streamable_http_transport import McpStreamableHttpTransport
from mark.mcp.types import McpServerConfig, McpTransportKind
from mark.mcp.transport import McpStdioTransport


class TestStreamableHttpImport:
    """Verify streamable HTTP transport module imports without conflicts."""

    def test_mcp_streamable_http_transport_class_exists(self) -> None:
        """McpStreamableHttpTransport class is importable."""
        assert McpStreamableHttpTransport is not None

    def test_streamable_http_transport_instantiation(self) -> None:
        """Transport can be instantiated with a URL."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        assert transport.url == "http://localhost:3001/mcp"
        assert transport._closed is False
        assert transport._write_stream is None


class TestStreamableHttpClientConfig:
    """Tests that McpClient selects streamable HTTP transport correctly."""

    def test_client_selects_http_transport(self) -> None:
        """McpClient chooses streamable_http based on config."""
        config = McpServerConfig(
            name="http_test",
            transport=McpTransportKind.STREAMABLE_HTTP,
            url="http://localhost:3001/mcp",
        )
        client = McpClient(config)
        transport = client._create_transport()
        assert isinstance(transport, McpStreamableHttpTransport)

    def test_client_selects_stdio_transport(self) -> None:
        """McpClient chooses stdio based on config."""
        import sys
        config = McpServerConfig(
            name="stdio_test",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        client = McpClient(config)
        transport = client._create_transport()
        assert isinstance(transport, McpStdioTransport)


class TestStreamableHttpConnectionFailure:
    """Tests for streamable HTTP connection failure handling."""

    @pytest.mark.asyncio
    async def test_connect_to_nonexistent_server_fails_gracefully(self) -> None:
        """Connection to a server that does not exist raises a descriptive error."""
        transport = McpStreamableHttpTransport("http://localhost:19999/nonexistent")
        with pytest.raises(RuntimeError, match="Streamable HTTP connection failed"):
            await transport.start()


class TestStreamableHttpTransportMethods:
    """Tests for McpStreamableHttpTransport method availability."""

    def test_transport_has_required_methods(self) -> None:
        """Transport exposes all methods expected by McpClient."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        assert hasattr(transport, "start")
        assert hasattr(transport, "stop")
        assert hasattr(transport, "send_message")
        assert hasattr(transport, "cancel_request")
        assert hasattr(transport, "is_connected")

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self) -> None:
        """Calling stop() before start() does not crash."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        await transport.stop()

    @pytest.mark.asyncio
    async def test_stop_after_start_fails_gracefully(self) -> None:
        """Stopping a transport that failed to start is safe."""
        transport = McpStreamableHttpTransport("http://localhost:19999/nonexistent")
        try:
            await transport.start()
        except RuntimeError:
            pass
        await transport.stop()
        assert transport._closed is True

    def test_is_connected_initially_false(self) -> None:
        """Transport reports disconnected before start()."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        assert transport.is_connected is False

    def test_headers_propagate(self) -> None:
        """Custom headers are stored in transport."""
        transport = McpStreamableHttpTransport(
            "http://localhost:3001/mcp",
            headers={"Authorization": "Bearer test"},
        )
        assert transport._headers["Authorization"] == "Bearer test"

    def test_timeout_config_defaults(self) -> None:
        """Timeout parameters are stored correctly."""
        transport = McpStreamableHttpTransport(
            "http://localhost:3001/mcp",
            connect_timeout=5.0,
            read_timeout=20.0,
        )
        assert transport._connect_timeout == 5.0
        assert transport._read_timeout == 20.0

    def test_make_timeout_produces_httpx_timeout(self) -> None:
        """_make_timeout creates a valid httpx Timeout object."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        import httpx
        timeout = transport._make_timeout()
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.connect == 10.0
        assert timeout.read == 30.0

    def test_make_timeout_with_override(self) -> None:
        """_make_timeout accepts read override."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        import httpx
        timeout = transport._make_timeout(read_override=60.0)
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.read == 60.0


class TestStreamableHttpTransportTimeoutConfig:
    """Tests for timeout parameter validation and usage."""

    def test_all_timeout_params_stored(self) -> None:
        """All four timeout params are stored."""
        transport = McpStreamableHttpTransport(
            "http://localhost:3001/mcp",
            connect_timeout=2.0,
            read_timeout=5.0,
            write_timeout=10.0,
            pool_timeout=3.0,
        )
        assert transport._connect_timeout == 2.0
        assert transport._read_timeout == 5.0
        assert transport._write_timeout == 10.0
        assert transport._pool_timeout == 3.0


class TestMcpStreamableHttpTransportAsyncContext:
    """Tests for async context manager protocol."""

    @pytest.mark.asyncio
    async def test_aenter_raises_on_bad_server(self) -> None:
        """__aenter__ raises on connection failure."""
        transport = McpStreamableHttpTransport("http://localhost:19999/nonexistent")
        with pytest.raises(RuntimeError, match="Streamable HTTP connection failed"):
            await transport.__aenter__()

    @pytest.mark.asyncio
    async def test_closed_property_after_stop(self) -> None:
        """_closed flag is True after stop()."""
        transport = McpStreamableHttpTransport("http://localhost:3001/mcp")
        assert transport._closed is False
        await transport.stop()
        assert transport._closed is True


class TestStreamableHttpMcpClientIntegration:
    """Integration tests between McpClient and streamable HTTP transport."""

    def test_http_config_cannot_invoke_stdio_args(self) -> None:
        """STREAMABLE_HTTP config rejects stdio-only fields."""
        config = McpServerConfig(
            name="http",
            transport=McpTransportKind.STREAMABLE_HTTP,
            url="http://localhost:3001/mcp",
            # command and args should be ignored for HTTP transport
        )
        client = McpClient(config)
        transport = client._create_transport()
        assert isinstance(transport, McpStreamableHttpTransport)
        assert transport.url == "http://localhost:3001/mcp"
