"""E2E tests for MCP integration with SlonAG ToolRegistry, SafetyPolicy, and ToolExecutor.

Tests the full chain:
    MCP server -> discovery -> ToolRegistry.register -> SafetyPolicy -> ToolExecutor -> ToolResult
"""

from __future__ import annotations

import sys
import pytest

from mark.mcp.integration import McpIntegration
from mark.mcp.types import McpServerConfig, McpTransportKind
from mark.safety.policy import SafetyPolicy
from mark.tools.contracts import ToolResult
from mark.tools.executor import ToolExecutor
from mark.tools.registry import ToolRegistry
from mark.tools.builtin import build_builtin_registry


def _make_test_config(**overrides: object) -> McpServerConfig:
    base = {
        "name": "test",
        "transport": McpTransportKind.STDIO,
        "command": sys.executable,
        "args": ["-m", "mark.mcp.test_server"],
        "tool_timeout_seconds": 10.0,
        "init_timeout_seconds": 5.0,
    }
    base.update(overrides)
    return McpServerConfig(**base)  # type: ignore[arg-type]


class TestMcpIntegrationLifecycle:
    """Tests for the full MCP integration lifecycle."""

    @pytest.mark.asyncio
    async def test_integration_start_discover_invoke(self) -> None:
        """MCP integration: start -> discover tools in registry -> invoke via handler."""
        policy = SafetyPolicy()
        shared_registry = build_builtin_registry()
        executor = ToolExecutor(shared_registry, policy)

        config = _make_test_config()
        integration = McpIntegration.create(
            config,
            safety_policy=policy,
            tool_executor=executor,
        )

        await integration.start()
        assert integration.client is not None
        assert integration.client.is_initialized

        specs = await integration.discover_tools()
        assert len(specs) >= 3

        # Verify tools are in the shared registry (via integration's _registry)
        registry_tools = integration._registry.list()
        registry_names = {s.name for s in registry_tools}
        assert any("echo" in n for n in registry_names)
        assert any("compute" in n for n in registry_names)
        assert any("write_note" in n for n in registry_names)

        # Find the echo handler in the integration registry
        echo_spec = None
        for s in registry_tools:
            if "echo" in s.name:
                echo_spec = s
                break
        assert echo_spec is not None
        assert echo_spec.handler is not None

        # Invoke through the handler
        result = await echo_spec.handler(message="hello from integration test")
        assert isinstance(result, ToolResult)
        assert result.ok
        assert "hello from integration test" in str(result.message)

        await integration.stop()

    @pytest.mark.asyncio
    async def test_safety_policy_gates_mcp_tool(self) -> None:
        """SafetyPolicy gates MCP tool invocations through invoke_tool."""
        config = _make_test_config()
        integration = McpIntegration.create(
            config,
            safety_policy=SafetyPolicy(),
        )

        await integration.start()
        specs = await integration.discover_tools()
        assert len(specs) >= 3

        result = await integration.invoke_tool(
            "test_echo",
            {"message": "test"},
        )
        assert result.ok

        await integration.stop()

    @pytest.mark.asyncio
    async def test_mcp_integration_not_initialized(self) -> None:
        """invoke_tool on unstarted integration returns error."""
        config = _make_test_config()
        integration = McpIntegration.create(config)

        result = await integration.invoke_tool(
            "test_echo",
            {"message": "nope"},
        )
        assert not result.ok
        assert result.code == "mcp_not_initialized"

    @pytest.mark.asyncio
    async def test_mcp_integration_stop_releases_client(self) -> None:
        """Stopping the integration releases the MCP client."""
        config = _make_test_config()
        integration = McpIntegration.create(config)

        await integration.start()
        assert integration.client is not None

        await integration.stop()
        assert integration.client is None
        assert not integration.has_tools()


class TestMcpIntegrationWithSafety:
    """Tests for SafetyPolicy integration with MCP tools."""

    @pytest.mark.asyncio
    async def test_mcp_tool_through_safety(self) -> None:
        """MCP tool invocation flows through SafetyPolicy.authorize()."""
        config = _make_test_config()
        policy = SafetyPolicy()
        shared_registry = ToolRegistry()

        integration = McpIntegration.create(
            config,
            safety_policy=policy,
            registry=shared_registry,
        )

        await integration.start()
        specs = await integration.discover_tools()
        assert len(specs) >= 3

        # Get the handler from the shared registry (ToolSpec), not from McpToolSpec
        echo_spec = None
        for s in shared_registry.list():
            if "echo" in s.name:
                echo_spec = s
                break
        assert echo_spec is not None
        assert echo_spec.handler is not None

        result = await echo_spec.handler(message="safety test")
        assert isinstance(result, ToolResult)
        assert result.ok

        await integration.stop()


class TestMcpIntegrationRegistrySharing:
    """Tests that MCP tools flow into the shared registry used by AgentLoop."""

    @pytest.mark.asyncio
    async def test_agentloop_sees_mcp_tools(self) -> None:
        """MCP tools registered in the shared registry are discoverable via registry.list()."""
        shared_registry = build_builtin_registry()
        config = _make_test_config()
        integration = McpIntegration.create(config, registry=shared_registry)

        await integration.start()
        await integration.discover_tools()

        specs = shared_registry.list()
        spec_names = [s.name for s in specs]

        # Should include both builtin tools and MCP tools
        assert any("echo" in n for n in spec_names)
        assert any("compute" in n for n in spec_names)
        assert any("write_note" in n for n in spec_names)
        # Should also include builtins from build_builtin_registry
        assert len(specs) >= 4

        await integration.stop()

    @pytest.mark.asyncio
    async def test_no_duplicate_registration(self) -> None:
        """Calling discover_tools twice does not register duplicate tools."""
        shared_registry = build_builtin_registry()
        config = _make_test_config()
        integration = McpIntegration.create(config, registry=shared_registry)

        await integration.start()
        await integration.discover_tools()
        first_count = len(shared_registry.list())

        await integration.discover_tools()
        second_count = len(shared_registry.list())

        assert first_count == second_count

        await integration.stop()
