"""MCP integration for SlonAG.

Exposes MCP server connections as discoverable and callable tools within the
AgentLoop.  MCP tool invocation is gated by the existing SafetyPolicy,
DurableApprovalCoordinator and ToolExecutor so that MCP tools never bypass
SlonAG security boundaries.
"""

from __future__ import annotations

from acta.mcp.client import McpClient
from acta.mcp.integration import McpIntegration
from acta.mcp.streamable_http_transport import McpStreamableHttpTransport
from acta.mcp.transport import McpStdioTransport

__all__ = [
    "McpClient",
    "McpIntegration",
    "McpStdioTransport",
    "McpStreamableHttpTransport",
]
