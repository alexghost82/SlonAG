"""Canonical, provider-neutral contracts for tool execution."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from mark.safety.types import RiskLevel


_TOOL_NAME_PATTERN = re.compile(r"^[a-z0-9_.-]+$")


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata and handler for one canonical tool."""

    name: str
    description: str
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object] | None
    handler: Callable[..., object]
    risk: RiskLevel
    timeout_seconds: float = 30.0
    read_only: bool = False
    idempotent: bool = False
    side_effects: bool = True
    parallel_safe: bool = False
    cancellable: bool = False
    capabilities: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _TOOL_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("tool name must match ^[a-z0-9_.-]+$")
        if not self.timeout_seconds > 0:
            raise ValueError("tool timeout_seconds must be greater than zero")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to an artifact produced by a tool."""

    kind: str
    path: str | None = None
    uri: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """Normalized outcome returned by every tool execution."""

    ok: bool
    code: str
    message: str = ""
    data: object | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    warnings: tuple[str, ...] = ()
    started_at: float | None = None
    finished_at: float | None = None
    retryable: bool = False


__all__ = ["ArtifactRef", "ToolResult", "ToolSpec"]
