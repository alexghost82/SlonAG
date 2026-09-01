"""Structured errors raised by the canonical tool runtime."""

from __future__ import annotations

from i18n import t

CODE_DUPLICATE_TOOL = "duplicate_tool"
CODE_UNKNOWN_TOOL = "unknown_tool"

_MESSAGES: dict[str, str] = {
    CODE_DUPLICATE_TOOL: t("tools.already_registered"),
    CODE_UNKNOWN_TOOL: t("tools.unknown"),
}


class ToolRegistryError(Exception):
    """Base class for registry errors with stable, non-sensitive codes."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message if message is not None else _MESSAGES[code])


class DuplicateToolError(ToolRegistryError):
    """A tool with the same canonical name is already registered."""

    def __init__(self, tool_name: str, message: str | None = None) -> None:
        self.tool_name = tool_name
        super().__init__(CODE_DUPLICATE_TOOL, message)


class UnknownToolError(ToolRegistryError):
    """The requested tool name is not registered."""

    def __init__(self, tool_name: str, message: str | None = None) -> None:
        self.tool_name = tool_name
        super().__init__(CODE_UNKNOWN_TOOL, message)


__all__ = [
    "CODE_DUPLICATE_TOOL",
    "CODE_UNKNOWN_TOOL",
    "DuplicateToolError",
    "ToolRegistryError",
    "UnknownToolError",
]
