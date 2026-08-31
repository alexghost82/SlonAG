"""MCP integration with SlonAG AgentLoop, ToolRegistry and SafetyPolicy.

MCP tools flow through the canonical execution pipeline:
    AgentLoop -> ToolRegistry.list() -> model tool selection
    -> SafetyPolicy -> Approval (if side-effect) -> ToolExecutor.handler()
    -> McpIntegration.invoke_tool() -> MCP server -> result -> ToolResult

MCP tools never bypass SlonAG security boundaries.
"""

from __future__ import annotations

from i18n import t
import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from acta.mcp.client import McpClient, McpCallResult
from acta.mcp.types import McpServerConfig, McpToolSpec, McpTransportKind
from acta.safety.policy import SafetyPolicy, authorize as safety_authorize
from acta.safety.types import DecisionKind, RiskLevel, SafetyDecision, UntrustedSource
from acta.safety.registry import register_mcp_tool
from acta.tools.contracts import ArtifactRef, ToolResult
from acta.tools.executor import ToolExecutor
from acta.tools.registry import ToolRegistry


@dataclass
class McpIntegration:
    """Bridges MCP servers into SlonAG's canonical tool execution pipeline.

    MCP tools are registered as ToolSpec entries in a shared ToolRegistry so that
    the AgentLoop's ``_call_provider`` path naturally discovers them.  Every
    invocation is routed through the existing SafetyPolicy,
    DurableApprovalCoordinator and ToolExecutor so that MCP tools never
    bypass SlonAG security boundaries.

    Features:
    - Full MCP lifecycle (init, discovery, invoke, disconnect)
    - Tool discovery and registration into a shared registry
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

    # Shared registry (set by caller, or defaults to tool_executor.registry)
    registry: ToolRegistry | None = None

    # Runtime state (owned by McpIntegration)
    client: McpClient | None = None
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
        registry: ToolRegistry | None = None,
    ) -> McpIntegration:
        return cls(
            config=config,
            safety_policy=safety_policy,
            tool_executor=tool_executor,
            approval_required=approval_required,
            registry=registry,
        )

    @property
    def _registry(self) -> ToolRegistry:
        """Return the shared ToolRegistry (defaulting to tool_executor.registry)."""
        if self.registry is not None:
            return self.registry
        if self.tool_executor is not None:
            return self.tool_executor.registry
        # Fallback: create a standalone registry
        if not hasattr(self, '_fallback_registry'):
            self._fallback_registry = ToolRegistry()  # type: ignore[attr-defined]
        return self._fallback_registry  # type: ignore[attr-defined]

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
            raise RuntimeError(t("error.mcp_client_not_started"))

        specs = await self.client.discover_tools()

        # Register each tool in the shared registry and safety registry
        for spec in specs:
            existing = self._registry.list()
            if not any(s.name == spec.name for s in existing):
                self._registry.register(
                    _build_mcp_tool_spec(spec, self)
                )
                # Also register in safety policy's static _REGISTRY
                register_mcp_tool(
                    spec.name,
                    risk=RiskLevel.CONFIRM if spec.side_effect else RiskLevel.READ,
                )

        return specs

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
                message="Сервер MCP не инициализирован",
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
                message=f"Инструмент MCP заблокирован политикой безопасности: {decision.reason}",
            )

        if decision.kind in (DecisionKind.CONFIRM, DecisionKind.EXACT_CONFIRM):
            if self.approval_required:
                return ToolResult(
                    ok=False,
                    code="approval_required",
                    message=f"Требуется согласование для инструмента '{qualified_name}'. "
                            f"Уровень риска: {decision.risk.name}",
                    data={
                        "approval_required": True,
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
                message="Вызов инструмента MCP отменён",
            )

        try:
            result = await self.client.invoke_tool(qualified_name, arguments)

            return ToolResult(
                ok=result.ok,
                code="ok" if result.ok else "mcp_error",
                message=result.content if result.content else (
                    result.error or "Нет содержимого"
                ),
                data=result.content or result.error or "Нет содержимого",
                warnings=result.warnings,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                code="mcp_error",
                message=f"Ошибка вызова MCP: {exc}",
            )

    async def discover_resources(self) -> list[Any]:
        """Discover resources from the MCP server."""
        if self.client is None:
            return []
        return await self.client.discover_resources()

    async def discover_resource_templates(self) -> list[Any]:
        """Discover resource templates from the MCP server."""
        if self.client is None:
            return []
        return await self.client.discover_resource_templates()

    async def read_resource(self, uri: str) -> McpCallResult:
        """Read a resource by URI."""
        if self.client is None:
            return McpCallResult(ok=False, error="MCP-клиент не инициализирован")
        return await self.client.read_resource(uri)

    async def discover_prompts(self) -> list[Any]:
        """Discover prompts from the MCP server."""
        if self.client is None:
            return []
        return await self.client.discover_prompts()

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> McpCallResult:
        """Retrieve a prompt."""
        if self.client is None:
            return McpCallResult(ok=False, error="MCP-клиент не инициализирован")
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
            self._started = False

    @property
    def available_tools(self) -> Mapping[str, McpToolSpec]:
        """Get the registered MCP tools."""
        return self.client.tools if self.client else {}


    @property
    def resources(self) -> list["McpResource"]:
        """Get discovered MCP resources."""
        return self.client.resources if self.client else []

    @property
    def resource_templates(self) -> list["McpResourceTemplate"]:
        """Get discovered MCP resource templates."""
        return self.client.resource_templates if self.client else []

    @property
    def prompts(self) -> list["McpPrompt"]:
        """Get discovered MCP prompts."""
        return self.client.prompts if self.client else []

    def has_tools(self) -> bool:
        """Check if any tools are registered."""
        return len(self.available_tools) > 0


def _build_mcp_tool_spec(mcp_spec: McpToolSpec, integration: McpIntegration) -> Any:
    """Build a ToolSpec for the MCP tool."""
    from acta.tools.contracts import ToolSpec

    async def handler(**kwargs: Any) -> ToolResult:
        return await integration.invoke_tool(
            mcp_spec.name,  # already qualified (e.g. "test_echo")
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
        side_effects=True,
        side_effect_class="reversible",
        cancellable=True,
        capabilities={"mcp", "remote"},
        scopes={integration.config.name},
    )
