"""MCP types and configuration for SlonAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from acta.safety.types import RiskLevel


class McpTransportKind(StrEnum):
    """Supported MCP transport mechanisms."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


@dataclass(frozen=True)
class McpToolSpec:
    """Resolved tool from MCP server discovery."""

    name: str
    description: str
    input_schema: dict[str, Any]
    risk: RiskLevel = RiskLevel.READ
    side_effect: bool = True
    side_effect_class: str = "reversible"


@dataclass
class McpResourceTemplate:
    """Resource template from MCP server discovery."""

    uri_pattern: str
    name: str
    description: str | None = None
    mime_type: str | None = None


@dataclass
class McpResource:
    """Resource from MCP server discovery."""

    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None
    uri_template: str | None = None


@dataclass
class McpPrompt:
    """Prompt from MCP server discovery."""

    name: str
    description: str | None = None
    arguments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class McpServerConfig:
    """Configuration for one MCP server connection."""

    name: str
    transport: McpTransportKind = McpTransportKind.STDIO
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    tool_timeout_seconds: float = 60.0
    init_timeout_seconds: float = 30.0
    max_concurrent: int = 4
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    denied_tools: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.command and self.transport != McpTransportKind.STDIO:
            raise ValueError(
                f"Command requires stdio transport; got {self.transport.value}"
            )
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent должен быть >= 1")
        if self.transport == McpTransportKind.STREAMABLE_HTTP and not self.url:
            raise ValueError("STREAMABLE_HTTP-транспорт требует URL")
