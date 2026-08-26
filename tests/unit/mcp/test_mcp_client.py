"""Tests for mark/mcp/client.py."""

from __future__ import annotations

import asyncio
import sys
import pytest

from mark.mcp.client import McpClient, McpCallResult
from mark.mcp.types import McpServerConfig, McpTransportKind


def _make_config() -> McpServerConfig:
    return McpServerConfig(
        name="test",
        transport=McpTransportKind.STDIO,
        command=sys.executable,
        args=["-m", "mark.mcp.test_server"],
        tool_timeout_seconds=10.0,
        init_timeout_seconds=5.0,
    )


class TestMcpClientLifecycle:
    """Tests for MCP client lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        client = McpClient(_make_config())
        async with client:
            assert client.is_initialized

    @pytest.mark.asyncio
    async def test_double_start(self) -> None:
        client = McpClient(_make_config())
        await client.start()
        await client.start()  # Should not raise
        assert client.is_initialized
        await client.stop()

    @pytest.mark.asyncio
    async def test_initialized_after_start(self) -> None:
        client = McpClient(_make_config())
        await client.start()
        assert client.is_initialized
        assert client._server_info.get("name") == "slon-test-mcp"
        assert client._server_version == "1.0.0"
        await client.stop()


class TestMcpToolDiscovery:
    """Tests for MCP tool discovery."""

    @pytest.mark.asyncio
    async def test_discover_tools(self) -> None:
        client = McpClient(_make_config())
        async with client:
            tools = await client.discover_tools()
            assert len(tools) >= 3
            names = [t.name for t in tools]
            assert any("echo" in n for n in names)
            assert any("compute" in n for n in names)
            assert any("write_note" in n for n in names)
            assert any("slow_operation" in n for n in names)

    @pytest.mark.asyncio
    async def test_tools_are_namespaced(self) -> None:
        client = McpClient(_make_config())
        async with client:
            tools = await client.discover_tools()
            for t in tools:
                assert t.name.startswith("test_")

    @pytest.mark.asyncio
    async def test_list_tools_format(self) -> None:
        client = McpClient(_make_config())
        async with client:
            tools = await client.list_tools()
            assert len(tools) >= 3
            for t in tools:
                assert "name" in t
                assert "description" in t
                assert "input_schema" in t


class TestMcpToolInvocation:
    """Tests for MCP tool invocation."""

    @pytest.mark.asyncio
    async def test_invoke_echo(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_echo", {"message": "hello"})
            assert result.ok
            assert result.content is not None
            assert "hello" in result.content

    @pytest.mark.asyncio
    async def test_invoke_compute_add(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_compute", {
                "operation": "add",
                "a": 2,
                "b": 3,
            })
            assert result.ok
            assert "5" in result.content

    @pytest.mark.asyncio
    async def test_invoke_compute_multiply(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_compute", {
                "operation": "multiply",
                "a": 4,
                "b": 5,
            })
            assert result.ok
            assert "20" in result.content

    @pytest.mark.asyncio
    async def test_invoke_compute_divide_by_zero(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_compute", {
                "operation": "divide",
                "a": 10,
                "b": 0,
            })
            assert not result.ok

    @pytest.mark.asyncio
    async def test_invoke_unknown_tool(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_nonexistent", {})
            assert not result.ok
            assert "unknown" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invoke_write_note(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_write_note", {
                "title": "Test Note",
                "content": "Hello world",
            })
            assert result.ok

    @pytest.mark.asyncio
    async def test_invoke_with_tool_call_id(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_echo", {"message": "test"})
            assert result.ok



class TestMcpResourceDiscovery:
    """Tests for MCP resource discovery."""

    @pytest.mark.asyncio
    async def test_discover_resources(self) -> None:
        client = McpClient(_make_config())
        async with client:
            resources = await client.discover_resources()
            assert len(resources) >= 1
            uris = [r.uri for r in resources]
            assert "memo://test/note" in uris

    @pytest.mark.asyncio
    async def test_discover_resource_templates(self) -> None:
        client = McpClient(_make_config())
        async with client:
            templates = await client.discover_resource_templates()
            assert len(templates) >= 1
            assert any("memo://test/{id}" in t.uri_pattern for t in templates)

    @pytest.mark.asyncio
    async def test_read_resource(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_resources()
            result = await client.read_resource("memo://test/note")
            assert result.ok
            assert len(result.resources) >= 1
            assert "test memo content" in result.resources[0].get("content", "")

    @pytest.mark.asyncio
    async def test_read_unknown_resource(self) -> None:
        client = McpClient(_make_config())
        async with client:
            result = await client.read_resource("memo://unknown/note")
            assert result.ok  # Server returns empty, not error
            assert len(result.resources) == 0


class TestMcpPromptDiscovery:
    """Tests for MCP prompt discovery."""

    @pytest.mark.asyncio
    async def test_discover_prompts(self) -> None:
        client = McpClient(_make_config())
        async with client:
            prompts = await client.discover_prompts()
            assert len(prompts) >= 1
            assert prompts[0].name == "summarize"

    @pytest.mark.asyncio
    async def test_get_prompt(self) -> None:
        client = McpClient(_make_config())
        async with client:
            await client.discover_prompts()
            result = await client.get_prompt("test_summarize", {
                "text": "Hello world this is a test",
            })
            assert result.ok
            assert len(result.prompts) >= 1


class TestMcpNamespaceCollision:
    """Tests for namespace collision handling."""

    @pytest.mark.asyncio
    async def test_different_servers_different_namespaces(self) -> None:
        """Two clients with different names should not clash."""
        config_a = McpServerConfig(
            name="Alpha Server",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        config_b = McpServerConfig(
            name="Beta Server",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
        )
        client_a = McpClient(config_a)
        client_b = McpClient(config_b)

        async with client_a, client_b:
            tools_a = await client_a.discover_tools()
            tools_b = await client_b.discover_tools()
            names_a = {t.name for t in tools_a}
            names_b = {t.name for t in tools_b}
            # No overlap
            assert len(names_a & names_b) == 0


class TestMcpBoundedResponses:
    """Tests for bounded response handling."""

    @pytest.mark.asyncio
    async def test_max_response_chars(self) -> None:
        long_text = "x" * 10000
        client = McpClient(_make_config(), max_tool_response_chars=100)
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("test_echo", {"message": long_text})
            assert result.ok
            assert result.content is not None
            assert len(result.content) <= 100


class TestMcpToolFiltering:
    """Tests for tool allow/deny filtering in config."""

    @pytest.mark.asyncio
    async def test_allowed_tools_filter(self) -> None:
        config = McpServerConfig(
            name="filtered",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
            allowed_tools=frozenset(["echo"]),
        )
        client = McpClient(config)
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("filtered_echo", {"message": "ok"})
            assert result.ok
            result2 = await client.invoke_tool("filtered_compute", {"operation": "add", "a": 1, "b": 2})
            assert not result2.ok
            assert "allowed" in result2.error.lower()

    @pytest.mark.asyncio
    async def test_denied_tools_filter(self) -> None:
        config = McpServerConfig(
            name="filtered",
            transport=McpTransportKind.STDIO,
            command=sys.executable,
            args=["-m", "mark.mcp.test_server"],
            denied_tools=frozenset(["compute"]),
        )
        client = McpClient(config)
        async with client:
            await client.discover_tools()
            result = await client.invoke_tool("filtered_compute", {"operation": "add", "a": 1, "b": 2})
            assert not result.ok
            assert "denied" in result.error.lower()
