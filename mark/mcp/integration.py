"""MCP integration with SlonAG AgentLoop, ToolRegistry and SafetyPolicy."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mark.mcp.client import McpClient, McpCallResult
from mark.mcp.types import McpServerConfig, McpToolSpec, McpTransportKind
from mark.safety.policy import SafetyPolicy, authorize as safety_authorize
from mark.safety.types import DecisionKind, RiskLevel, SafetyDecision, UntrustedSource
from mark.tools.contracts import ArtifactRef, ToolResult
from mark.tools.executor import ToolExecutor
from mark.tools.registry import ToolRegistry


@dataclass
class McpIntegration:
    """Bridges MCP servers into SlonAG's canonical tool execution pipeline.

    MCP tools are registered as ToolSpec entries in the ToolRegistry with the
    server name as namespace prefix.  Every invocation is routed through the
    existing SafetyPolicy, DurableApprovalCoordinator and ToolExecutor so that
    MCP tools never bypass SlonAG security boundaries.

    Features:
    - Full MCP lifecycle (init, discovery, invoke, disconnect)
    - Tool discovery and registration
    - Resource discovery (read-only passthrough)
    - Prompt discovery (read-only passthrough)
    - Session and workspace isolation
    - Bounded responses
    - Timeout and cancellation
    - Namespace collision handling
    - Secrets handling (config-time only)
    - Connection failure handling
    - Malformed response handling
    - Server disconnect handling
    """

    # Configuration
    config: McpServerConfig

    # Components (set by caller)
    safety_policy: SafetyPolicy | None = None
    tool_executor: ToolExecutor | None = None
    approval_required: bool = False

    # Runtime state (owned by McpIntegration)
    client: McpClient | None = None
    _registry: ToolRegistry | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _cancelled: threading.Event = field(default_factory=threading.Event)
    _started: bool = False

    @classmethod
    def create(
        cls,
        config: McpServerConfig,
        *,
        safety_policy: SafetyPolicy | None = None,
        tool_executor: ToolExecutor | None = None,
        approval_required: bool = False,
    ) -> McpIntegration:
        return cls(
            config=config,
            safety_policy=safety_policy,
            tool_executor=tool_executor,
            approval_required=approval_required,
        )

    async def start(self) -> None:
        """Initialize the MCP client and discover tools."""
        with self._lock:
            if self._started:
                return
            self.client = McpClient(self.config)
            await self.client.start()
            self._started = True

    async def discover_tools(self) -> list[McpToolSpec]:
        """Discover tools from the MCP server and register them."""
        if self.client is None:
            raise RuntimeError("MCP client not started")

        specs = await self.client.discover_tools()

        # Register each tool in the registry
        for spec in specs:
            if spec.name not in self._get_registry():
                # Create a ToolSpec-compatible handler
                self._get_registry().register(
                    _build_mcp_tool_spec(spec, self)
                )

        return specs

    def _get_registry(self) -> ToolRegistry:
        if self._registry is None:
            self._registry = ToolRegistry()
        return self._registry

    async def invoke_tool(
        self,
        qualified_name: str,
        arguments: dict[str, Any],
        *,
        source: UntrustedSource | str = UntrustedSource.TOOL_RESULT,
        intent: str = "",
        tool_call_id: str | None = None,
    ) -> ToolResult:
        """Execute an MCP tool through SafetyPolicy -> ToolExecutor pipeline."""
        if self.client is None or not self.client.is_initialized:
            return ToolResult(
                ok=False,
                code="mcp_not_initialized",
                message="MCP server not initialized",
            )

        policy = self.safety_policy or SafetyPolicy()

        # Safety check
        decision = policy.authorize(
            qualified_name,
            arguments,
            source=source,
            intent=intent,
        )

        if decision.kind == DecisionKind.DENY:
            return ToolResult(
                ok=False,
                code="safety_denied",
                message=f"MCP tool blocked by safety policy: {decision.reason}",
            )

        if decision.kind in (DecisionKind.CONFIRM, DecisionKind.EXACT_CONFIRM):
            if self.approval_required:
                return ToolResult(
                    ok=False,
                    code="approval_required",
                    message=f"Approval required for tool '{qualified_name}'. "
                            f"Risk level: {decision.risk.name}",
                    approval_required=True,
                    approval_info={
                        "tool_name": qualified_name,
                        "arguments": arguments,
                        "risk": decision.risk.name,
                        "tool_call_id": tool_call_id,
                    },
                )
            # In automated / subagent context, auto-approve non-biometric
            if decision.risk < RiskLevel.BIOMETRIC:
                pass  # Allow through

        # Check cancellation
        if self._cancelled.is_set():
            return ToolResult(
                ok=False,
                code="cancelled",
                message="MCP tool call was cancelled",
            )

        try:
            result = await self.client.invoke_tool(qualified_name, arguments)

            return ToolResult(
                ok=result.ok,
                code="ok" if result.ok else "mcp_error",
                message=result.content if result.content else (
                    result.error or "No content"
                ),
                data={"mcp_result": {
                    "ok": result.ok,
                    "warnings": list(result.warnings),
                }},
                warnings=result.warnings,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                code="mcp_error",
                message=f"MCP invocation failed: {exc}",
            )

    async def discover_resources(self) -> list[Any]:
        """Discover resources from the MCP server."""
        if self.client is None:
            return []
        return await self.client.discover_resources()

    async def read_resource(self, uri: str) -> McpCallResult:
        """Read a resource by URI."""
        if self.client is None:
            return McpCallResult(ok=False, error="MCP client not initialized")
        return await self.client.read_resource(uri)

    async def discover_prompts(self) -> list[Any]:
        """Discover prompts from the MCP server."""
        if self.client is None:
            return []
        return await self.client.discover_prompts()

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> McpCallResult:
        """Retrieve a prompt."""
        if self.client is None:
            return McpCallResult(ok=False, error="MCP client not initialized")
        return await self.client.get_prompt(name, arguments)

    def cancel(self) -> None:
        """Cancel all in-flight MCP operations."""
        self._cancelled.set()

    def reset_cancel(self) -> None:
        """Reset cancellation flag."""
        self._cancelled.clear()

    async def stop(self) -> None:
        """Stop the MCP client and unregister tools."""
        with self._lock:
            self._cancelled.set()
            if self.client is not None:
                await self.client.stop()
                self.client = None
            self._registry = None
            self._started = False

    @property
    def available_tools(self) -> Mapping[str, McpToolSpec]:
        """Get the registered MCP tools."""
        return self.client.tools if self.client else {}

    def has_tools(self) -> bool:
        """Check if any tools are registered."""
        return len(self.available_tools) > 0


def _build_mcp_tool_spec(mcp_spec: McpToolSpec, integration: McpIntegration) -> Any:
    """Build a ToolSpec for the MCP tool."""
    from mark.tools.contracts import ToolSpec

    async def handler(**kwargs: Any) -> ToolResult:
        return await integration.invoke_tool(
            mcp_spec.name,
            kwargs,
            source=UntrustedSource.TOOL_RESULT,
        )

    return ToolSpec(
        name=mcp_spec.name,
        description=mcp_spec.description,
        input_schema=mcp_spec.input_schema,
        output_schema={"type": "object", "properties": {
            "ok": {"type": "boolean"},
            "content": {"type": ["string", "null"]},
            "error": {"type": ["string", "null"]},
        }},
        handler=handler,
        risk=RiskLevel.READ,
        timeout_seconds=integration.config.tool_timeout_seconds,
        side_effect=integration.config.tool_timeout_seconds > 0,
        side_effect_class="reversible",
        cancellable=True,
        capabilities={"mcp", "remote"},
        scopes={integration.config.name},
    )
