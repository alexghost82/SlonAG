"""Tool specifications for the unified filesystem tool.

Each spec provides:
- name, description, input_schema, output_schema (provider-neutral)
- risk, side_effects, read_only, idempotent, cancellable
- handler reference (bound to filesystem_operation or individual ops)
"""

from __future__ import annotations

from collections.abc import Mapping

from acta.filesystem.operations import (
    FileSystemResult,
    copy,
    create_directory,
    create_file,
    delete,
    disk_usage,
    filesystem_operation,
    list_directory,
    metadata,
    move,
    organize_desktop,
    read,
    rename,
    search,
    trash,
    write,
)
from acta.safety.types import RiskLevel
from acta.tools.contracts import SideEffectClass, ToolSpec

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_PATH_SCHEMA = {
    "type": "string",
    "description": "Path to the file or directory. Supports shortcuts: desktop, downloads, documents, pictures, music, videos, home.",
}

_CONTENT_SCHEMA = {
    "type": "string",
    "description": "Content to write/create.",
}

_DESTINATION_SCHEMA = {
    "type": "string",
    "description": "Destination path for copy/move operations.",
}

_NAME_SCHEMA = {
    "type": "string",
    "description": "Name for create or rename operations.",
}

_PATTERN_SCHEMA = {
    "type": "string",
    "description": "Filename pattern to search for.",
}

_EXTENSION_SCHEMA = {
    "type": "string",
    "description": "File extension filter (without dot, e.g. 'py' or 'txt').",
}

_MAX_CHARS_SCHEMA = {
    "type": "integer",
    "description": "Maximum characters to read. Default 2097152 (2 MB).",
    "default": 2097152,
}

_MAX_RESULTS_SCHEMA = {
    "type": "integer",
    "description": "Maximum number of search results. Default 100.",
    "default": 100,
}

_SHOW_HIDDEN_SCHEMA = {
    "type": "boolean",
    "description": "Show hidden files (starting with dot).",
    "default": False,
}

_APPEND_SCHEMA = {
    "type": "boolean",
    "description": "Append content instead of overwriting.",
    "default": False,
}

_RECURSIVE_SCHEMA = {
    "type": "boolean",
    "description": "Delete directories recursively.",
    "default": False,
}

_COUNT_SCHEMA = {
    "type": "integer",
    "description": "Number of largest files to return.",
    "default": 10,
}


# ---------------------------------------------------------------------------
# Unified filesystem tool spec
# ---------------------------------------------------------------------------

_UNIFIED_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "Operation: read, write, create_file, create_directory, create_folder, list, list_directory, search, find, metadata, info, disk_usage, copy, move, rename, delete, trash, organize_desktop, largest, undo.",
            "enum": [
                "read", "write", "create_file", "create_folder", "create_directory",
                "list", "list_directory", "search", "find",
                "metadata", "info", "stat",
                "disk_usage",
                "copy", "move", "rename",
                "delete", "trash", "remove",
                "organize_desktop",
                "largest", "undo",
            ],
        },
        "path": _PATH_SCHEMA,
        "path_raw": _PATH_SCHEMA,  # Alias for path
        "content": _CONTENT_SCHEMA,
        "destination": _DESTINATION_SCHEMA,  # Alias for new_name in rename
        "name": _NAME_SCHEMA,  # Alias for name_pattern in search
        "new_name": _NAME_SCHEMA,
        "show_hidden": _SHOW_HIDDEN_SCHEMA,
        "extension": _EXTENSION_SCHEMA,
        "name_pattern": _PATTERN_SCHEMA,
        "max_chars": _MAX_CHARS_SCHEMA,
        "max_results": _MAX_RESULTS_SCHEMA,
        "append": _APPEND_SCHEMA,
        "recursive": _RECURSIVE_SCHEMA,
        "count": _COUNT_SCHEMA,
    },
    "required": ["action"],
    "additionalProperties": False,
}


def _filesystem_handler(args: Mapping[str, object]) -> FileSystemResult:
    """Unified handler that dispatches to filesystem_operation."""
    action = str(args.get("action", "")).strip().lower()
    kwargs: dict[str, object] = {}
    for key in ("path", "path_raw", "content", "destination", "name", "new_name",
                "show_hidden", "extension", "name_pattern", "max_chars",
                "max_results", "append", "recursive", "count"):
        if key in args and args[key] is not None:
            kwargs[key] = args[key]
    kwargs["roots"] = ()  # Uses default allowlist at runtime
    return filesystem_operation(action, **kwargs)


UNIFIED_FILESYSTEM_TOOL = ToolSpec(
    name="filesystem",
    description=(
        "Unified secure filesystem operations: read, write, create, list, search, "
        "metadata, copy, move, rename, trash, delete, organize. "
        "All paths are validated against the canonical allowlist and security policy."
    ),
    input_schema=_UNIFIED_SCHEMA,
    output_schema={
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "code": {"type": "string"},
            "message": {"type": "string"},
            "data": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    },
    handler=_filesystem_handler,
    risk=RiskLevel.CONFIRM,
    read_only=False,
    idempotent=False,
    side_effects=True,
    side_effect_class=SideEffectClass.REVERSIBLE,
    cancellable=True,
)


# ---------------------------------------------------------------------------
# Legacy alias tools (for backward compatibility)
# ---------------------------------------------------------------------------


def _read_file_handler(args: Mapping[str, object]) -> FileSystemResult:
    """Legacy read_file: narrow text read."""
    path = str(args.get("path", ""))
    max_chars = int(args.get("max_chars", 2097152))
    return read(path, max_chars=max_chars)


def _file_controller_handler(args: Mapping[str, object]) -> FileSystemResult:
    """Legacy file_controller: action-based interface."""
    action = str(args.get("action", "")).strip().lower()
    kwargs: dict[str, object] = {}
    for key in ("path", "path_raw", "content", "destination", "name", "new_name",
                "show_hidden", "extension", "name_pattern", "max_chars",
                "max_results", "append", "recursive", "count"):
        if key in args and args[key] is not None:
            kwargs[key] = args[key]
    kwargs["roots"] = ()
    return filesystem_operation(action, **kwargs)


READ_FILE_TOOL = ToolSpec(
    name="read_file",
    description="Read a text file with encoding validation.",
    input_schema={
        "type": "object",
        "properties": {
            "path": _PATH_SCHEMA,
            "max_chars": _MAX_CHARS_SCHEMA,
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    output_schema=UNIFIED_FILESYSTEM_TOOL.output_schema,
    handler=_read_file_handler,
    risk=RiskLevel.READ,
    read_only=True,
    idempotent=True,
    side_effects=False,
    side_effect_class=SideEffectClass.NONE,
    cancellable=True,
)

FILE_CONTROLLER_TOOL = ToolSpec(
    name="file_controller",
    description=(
        "Legacy file controller. Use 'filesystem' tool for new code. "
        "Action-based file operations with allowlist enforcement."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: list, read, write, create_file, create_folder, delete, move, copy, rename, find, info, disk_usage, organize_desktop, largest, undo.",
                "enum": [
                    "list", "read", "write", "create_file", "create_folder",
                    "delete", "move", "copy", "rename", "find",
                    "info", "disk_usage", "organize_desktop", "largest", "undo",
                ],
            },
            "path": _PATH_SCHEMA,
            "content": _CONTENT_SCHEMA,
            "destination": _DESTINATION_SCHEMA,
            "name": _NAME_SCHEMA,
            "show_hidden": _SHOW_HIDDEN_SCHEMA,
            "extension": _EXTENSION_SCHEMA,
            "max_results": _MAX_RESULTS_SCHEMA,
            "append": _APPEND_SCHEMA,
        },
        "required": ["action"],
        "additionalProperties": False,
    },
    output_schema=UNIFIED_FILESYSTEM_TOOL.output_schema,
    handler=_file_controller_handler,
    risk=RiskLevel.CONFIRM,
    read_only=False,
    idempotent=False,
    side_effects=True,
    side_effect_class=SideEffectClass.REVERSIBLE,
    cancellable=True,
)


__all__ = [
    "UNIFIED_FILESYSTEM_TOOL",
    "READ_FILE_TOOL",
    "FILE_CONTROLLER_TOOL",
    # Re-export individual tools for direct use
    "read",
    "write",
    "create_file",
    "create_directory",
    "list_directory",
    "search",
    "metadata",
    "disk_usage",
    "copy",
    "move",
    "rename",
    "trash",
    "delete",
    "organize_desktop",
]
