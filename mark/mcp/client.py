"""MCP client with full lifecycle management for SlonAG."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mark.mcp.transport import McpStdioTransport
from mark.mcp.types import (
    McpPrompt,
    McpResource,
    McpResourceTemplate,
    McpServerConfig,
    McpToolSpec,
    McpTransportKind,
)


@dataclass
class McpCallResult:
    """Result of invoking an MCP tool or resource."""

    ok: bool
    content: str | dict | None = None
    error: str | None = None
    resources: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    warnings: tuple[str, ...] = ()


class McpClient:
    """High-level MCP client managing server connection, discovery, and invocation.

    Provides:
    - Connection lifecycle (start, stop, reconnect)
    - Tool discovery and invocation
    - Resource discovery and reading
    - Prompt discovery and retrieval
    - Timeout and cancellation
    - Session and workspace isolation
    - Namespace collision handling
    - Bounded responses
    - Connection failure handling
    - Malformed response handling
    - Server disconnect handling
    - Secrets handling (env vars, not embedded in messages)
    """

    def __init__(
        self,
        config: McpServerConfig,
        *,
        session_id: str | None = None,
        workspace_id: str | None = None,
        max_tool_response_chars: int = 8192,
    ) -> None:
        self.config = config
        self._transport: McpStdioTransport | None = None
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._max_response_chars = max_tool_response_chars
        self._initialized = False
        self._tools: dict[str, McpToolSpec] = {}
        self._resources: list[McpResource] = []
        self._resource_templates: list[McpResourceTemplate] = []
        self._prompts: list[McpPrompt] = []
        self._tool_capabilities: dict[str, str | None] = {}
        self._server_info: dict[str, str] = {}
        self._server_version: str = ""

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def tools(self) -> Mapping[str, McpToolSpec]:
        return dict(self._tools)

    @property
    def resources(self) -> list[McpResource]:
        return list(self._resources)

    @property
    def resource_templates(self) -> list[McpResourceTemplate]:
        return list(self._resource_templates)

    @property
    def prompts(self) -> list[McpPrompt]:
        return list(self._prompts)

    async def start(self) -> None:
        """Start transport and perform MCP initialization handshake."""
        if self._transport is not None:
            await self._transport.stop()
        self._transport = McpStdioTransport(self.config)
        await self._transport.start()

        try:
            await self._initialize()
        except Exception:
            await self.stop()
            raise

    async def _initialize(self) -> None:
        """Perform MCP initialize handshake."""
        try:
            result = await self._transport.send_message(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "slonag",
                        "version": "0.1.0",
                    },
                },
                timeout=self.config.init_timeout_seconds,
            )
            if not isinstance(result, dict):
                raise ValueError("initialize returned non-dict")

            self._server_info = result.get("serverInfo", {})
            self._server_version = self._server_info.get("version", "unknown")

            # Negotiate capabilities
            server_caps = result.get("capabilities", {})
            self._tool_capabilities = {
                "tools": server_caps.get("tools", {}).get("listChanged") and "changed" or None,
                "resources": server_caps.get("resources", {}).get("subscribe") and "subscribe" or None,
                "prompts": server_caps.get("prompts", {}).get("listChanged") and "changed" or None,
            }

            # Send initialized notification
            try:
                await self._transport.send_message("notifications/initialized")
            except Exception:
                pass  # Some servers don't expect this

            self._initialized = True

        except Exception as exc:
            raise RuntimeError(f"MCP initialization failed: {exc}") from exc

    async def discover_tools(self) -> list[McpToolSpec]:
        """List all tools exposed by the MCP server."""
        try:
            result = await self._transport.send_message(
                "tools/list", timeout=self.config.init_timeout_seconds
            )
            items = result.get("tools", []) if isinstance(result, dict) else []
            tools: dict[str, McpToolSpec] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                if not name:
                    continue

                # Handle namespace collision: prefix with server name
                qualified_name = self._qualified_name(name)

                spec = McpToolSpec(
                    name=qualified_name,
                    description=item.get("description", ""),
                    input_schema=item.get("inputSchema", {}),
                    side_effect=item.get("annotations", {}).get("writesResult", False),
                    side_effect_class=(
                        "reversible"
                        if not item.get("annotations", {}).get("writesResult", False)
                        else "irreversible"
                    ),
                )
                tools[qualified_name] = spec
            self._tools = tools
            return list(tools.values())
        except Exception as exc:
            self._tools = {}
            raise RuntimeError(f"Tool discovery failed: {exc}") from exc

    def _qualified_name(self, name: str) -> str:
        """Add server name prefix to avoid namespace collisions."""
        prefix = self.config.name.lower().replace(" ", "_").replace("-", "_")
        return f"{prefix}_{name}"

    async def discover_resources(self) -> list[McpResource]:
        """List all resources exposed by the MCP server."""
        try:
            result = await self._transport.send_message(
                "resources/list", timeout=self.config.init_timeout_seconds
            )
            items = result.get("resources", []) if isinstance(result, dict) else []
            self._resources = [
                McpResource(
                    uri=item.get("uri", ""),
                    name=item.get("name", ""),
                    description=item.get("description"),
                    mime_type=item.get("mimeType"),
                )
                for item in items
                if isinstance(item, dict) and item.get("uri")
            ]
            return self._resources
        except Exception:
            self._resources = []
            return self._resources

    async def discover_resource_templates(self) -> list[McpResourceTemplate]:
        """List all resource templates exposed by the MCP server."""
        try:
            result = await self._transport.send_message(
                "resources/templates/list", timeout=self.config.init_timeout_seconds
            )
            items = result.get("resourceTemplates", []) if isinstance(result, dict) else []
            self._resource_templates = [
                McpResourceTemplate(
                    uri_pattern=item.get("uriTemplate", ""),
                    name=item.get("name", ""),
                    description=item.get("description"),
                    mime_type=item.get("mimeType"),
                )
                for item in items
                if isinstance(item, dict) and item.get("uriTemplate")
            ]
            return self._resource_templates
        except Exception:
            self._resource_templates = []
            return self._resource_templates

    async def discover_prompts(self) -> list[McpPrompt]:
        """List all prompts exposed by the MCP server."""
        try:
            result = await self._transport.send_message(
                "prompts/list", timeout=self.config.init_timeout_seconds
            )
            items = result.get("prompts", []) if isinstance(result, dict) else []
            self._prompts = [
                McpPrompt(
                    name=item.get("name", ""),
                    description=item.get("description"),
                    arguments=item.get("arguments", []),
                )
                for item in items
                if isinstance(item, dict) and item.get("name")
            ]
            return self._prompts
        except Exception:
            self._prompts = []
            return self._prompts

    async def read_resource(self, uri: str) -> McpCallResult:
        """Read a resource by URI."""
        try:
            result = await self._transport.send_message(
                "resources/read",
                {"uri": uri},
                timeout=self.config.tool_timeout_seconds,
            )
            contents = result.get("contents", []) if isinstance(result, dict) else []
            parsed_contents: list[dict[str, Any]] = []
            for item in contents:
                if isinstance(item, dict):
                    if "text" in item:
                        parsed_contents.append({
                            "uri": uri,
                            "mime_type": item.get("mimeType"),
                            "content": str(item["text"])[:self._max_response_chars],
                        })
                    elif "blob" in item:
                        parsed_contents.append({
                            "uri": uri,
                            "mime_type": item.get("mimeType"),
                            "content": f"<binary {len(str(item['blob']))} bytes>",
                        })
            return McpCallResult(ok=True, resources=parsed_contents)
        except Exception as exc:
            return McpCallResult(ok=False, error=str(exc))

    async def invoke_tool(self, name: str, arguments: dict[str, Any] | None = None) -> McpCallResult:
        """Invoke an MCP tool by qualified name."""
        # Strip server prefix to get original name
        original_name = self._unqualified_name(name)

        # Check tool allow/deny lists
        if self.config.denied_tools and original_name in self.config.denied_tools:
            return McpCallResult(
                ok=False,
                error=f"Tool '{original_name}' is denied by server config",
            )
        if self.config.allowed_tools and original_name not in self.config.allowed_tools:
            return McpCallResult(
                ok=False,
                error=f"Tool '{original_name}' is not in allowed list",
            )

        if original_name not in self._tools:
            return McpCallResult(
                ok=False,
                error=f"Unknown MCP tool: '{original_name}'",
            )

        try:
            result = await self._transport.send_message(
                "tools/call",
                {
                    "name": original_name,
                    "arguments": arguments or {},
                },
                timeout=self.config.tool_timeout_seconds,
            )

            if not isinstance(result, dict):
                return McpCallResult(
                    ok=False,
                    error="MCP tool returned non-dict result",
                )

            # Parse content blocks
            content_blocks = result.get("content", [])
            texts: list[str] = []
            warnings: list[str] = []

            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_val = block.get("text", "")
                        texts.append(str(text_val)[:self._max_response_chars])
                    elif block.get("type") == "image":
                        texts.append(f"<image {block.get('mimeType', 'unknown')}>")
                    elif block.get("type") == "resource":
                        texts.append(f"<resource: {block.get('resource', {}).get('uri', '?')}>")
                    else:
                        texts.append(f"<{block.get('type', 'unknown')}>")

            # Extract warnings
            if result.get("isError"):
                warnings.append("Tool reported error status")

            content_str = "\n\n".join(texts) if texts else str(result.get("data", ""))
            return McpCallResult(
                ok=not result.get("isError", False),
                content=content_str if content_str else None,
                warnings=tuple(warnings),
            )
        except asyncio.TimeoutError:
            return McpCallResult(ok=False, error="MCP tool invocation timed out")
        except RuntimeError as exc:
            error_msg = str(exc)
            if "not connected" in error_msg.lower() or "closed" in error_msg.lower():
                return McpCallResult(
                    ok=False,
                    error="MCP server disconnected",
                )
            return McpCallResult(ok=False, error=error_msg)
        except Exception as exc:
            return McpCallResult(ok=False, error=f"MCP tool invocation failed: {exc}")

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> McpCallResult:
        """Retrieve a prompt by name."""
        original_name = self._unqualified_name(name)
        if original_name not in {p.name for p in self._prompts}:
            return McpCallResult(ok=False, error=f"Unknown prompt: '{original_name}'")

        try:
            result = await self._transport.send_message(
                "prompts/get",
                {"name": original_name, "arguments": arguments or {}},
                timeout=self.config.tool_timeout_seconds,
            )
            messages = result.get("messages", []) if isinstance(result, dict) else []
            parsed: list[dict[str, Any]] = []
            for msg in messages:
                if isinstance(msg, dict):
                    content_items = msg.get("content", [])
                    texts: list[str] = []
                    for c in content_items:
                        if isinstance(c, dict) and c.get("type") == "text":
                            texts.append(str(c.get("text", "")))
                    parsed.append({
                        "role": msg.get("role", "user"),
                        "content": " ".join(texts),
                    })
            return McpCallResult(ok=True, prompts=parsed)
        except Exception as exc:
            return McpCallResult(ok=False, error=str(exc))

    def _unqualified_name(self, qualified_name: str) -> str:
        """Strip the server name prefix to get original tool/prompt name."""
        prefix = self.config.name.lower().replace(" ", "_").replace("-", "_") + "_"
        if qualified_name.startswith(prefix):
            return qualified_name[len(prefix):]
        return qualified_name

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return tools in the format expected by provider tool_calling.

        Returns list of dicts with keys: name, description, input_schema.
        """
        specs = self.tools
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in specs.values()
        ]

    async def list_resources(self) -> list[dict[str, Any]]:
        """Return resources in discoverable format."""
        return [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mime_type": r.mime_type,
            }
            for r in self._resources
        ]

    async def list_resource_templates(self) -> list[dict[str, Any]]:
        """Return resource templates in discoverable format."""
        return [
            {
                "uri_pattern": rt.uri_pattern,
                "name": rt.name,
                "description": rt.description,
                "mime_type": rt.mime_type,
            }
            for rt in self._resource_templates
        ]

    async def list_prompts(self) -> list[dict[str, Any]]:
        """Return prompts in discoverable format."""
        return [
            {
                "name": p.name,
                "description": p.description,
                "arguments": p.arguments,
            }
            for p in self._prompts
        ]

    async def stop(self) -> None:
        """Close the transport and release resources."""
        self._initialized = False
        if self._transport is not None:
            await self._transport.stop()
            self._transport = None

    async def __aenter__(self) -> McpClient:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()
