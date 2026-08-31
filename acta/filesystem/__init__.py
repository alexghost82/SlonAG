"""Canonical filesystem security module.

Exports:
- ``security``: path validation, traversal/symlink protection, size limits,
  encoding helpers, cancellation support.
- ``operations``: read, write, create, list, search, metadata, copy, move,
  rename, trash, delete, directory operations.
- ``tools``: ``ToolSpec`` definitions for the tool registry.

Usage::

    from acta.filesystem import security, operations, tools

    # Validate a path
    from acta.filesystem.security import validate_path, default_allowlist_roots
    roots = default_allowlist_roots()
    resolved = validate_path("my_file.txt", roots)

    # Perform an operation
    from acta.filesystem.operations import read, write, filesystem_operation
    result = read("my_file.txt", roots=roots)

    # Register in tool registry
    from acta.filesystem.tools import UNIFIED_FILESYSTEM_TOOL, READ_FILE_TOOL, FILE_CONTROLLER_TOOL
    registry.register(UNIFIED_FILESYSTEM_TOOL)

Security principles:
1. Deny by default — only user folders and workspace are allowed.
2. All paths are canonicalized via ``Path.resolve()`` before check.
3. Symlink chains are checked component-by-component.
4. System paths (/etc, /usr, /proc, etc.) are always denied.
5. Size limits enforce read/write ceilings.
6. Operations support cancellation via threading.Event.
7. Binary files are detected and rejected for text operations.
"""

from __future__ import annotations

from acta.filesystem import security, operations, tools

__all__ = [
    "security",
    "operations",
    "tools",
    # Re-export key items
    "security",
    "operations",
    "tools",
]
