# actions/file_controller.py
# File management — canonical paths, confirmed mutations, trash-only delete.
# This module provides the legacy action-layer API. All file operations are
# delegated to mark.filesystem which enforces the canonical security policy.

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mark.filesystem.security import (
    default_allowlist_roots,
)
from mark.filesystem.operations import (
    FileSystemResult,
    filesystem_operation,
    create_directory,
    create_file,
    delete,
    disk_usage,
    list_directory,
    metadata,
    organize_desktop,
    read,
    rename,
    search,
    trash,
    write,
)
from mark.safety import ArgValidationError, DecisionKind, authorize, validate_args
from mark.safety.types import SafetyDecision

try:
    import send2trash as send2trash_mod
except ImportError:
    send2trash_mod = None

send2trash = send2trash_mod

Confirmer = Callable[[SafetyDecision], bool]
TrashHook = Callable[[Path], None]
Logger = Callable[[str], None]

_TOOL = "file_controller"
_NEEDS_CONFIRM = frozenset(
    {
        DecisionKind.CONFIRM,
        DecisionKind.EXACT_CONFIRM,
        DecisionKind.BIOMETRIC,
    }
)


@dataclass
class _Hooks:
    allowlist: tuple[Path, ...]
    confirmer: Confirmer | None
    trash: TrashHook | None
    logger: Logger | None
    undo_stack: list[dict[str, Path]]
    player: Any = None
    source: str = "user"
    intent: str = ""
    logs: list[str] = field(default_factory=list)


_SHORTCUTS = {
    "desktop": "Desktop",
    "downloads": "Downloads",
    "documents": "Documents",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
    "home": "",
}


def _expand_shortcut_or_path(raw: str) -> Path:
    """Convert shortcut names to paths, keeping the security layer intact."""
    text = (raw or "").strip()
    if not text:
        return Path()
    key = text.lower()
    if key == "home":
        return Path.home()
    if key in _SHORTCUTS:
        return Path.home() / _SHORTCUTS[key]
    return Path(text).expanduser()


def _sanitize_allowlist(roots: Sequence[str | Path] | None) -> tuple[Path, ...]:
    if roots is None:
        return default_allowlist_roots()
    cleaned: list[Path] = []
    for root in roots:
        raw = str(root)
        try:
            resolved = Path(root).expanduser().resolve()
        except OSError:
            continue
        cleaned.append(resolved)
    return tuple(cleaned) if cleaned else default_allowlist_roots()


def _run_action(checked: dict[str, object], hooks: _Hooks) -> str:
    """Map legacy action names to the new filesystem operations."""
    action = (checked.get("action") or "").strip().lower()
    path_raw = str(checked.get("path") or "desktop")
    name = str(checked.get("name") or "")
    content = str(checked.get("content") or "")
    dest = str(checked.get("destination") or "")
    new_name = str(checked.get("new_name") or name)

    roots = hooks.allowlist

    # Log the action
    if hooks.logger is not None:
        hooks.logger(f"[file] {action} {path_raw}")

    # Map actions to filesystem_operation
    match action:
        case "list":
            show_hidden = bool(checked.get("show_hidden", False))
            result = list_directory(path_raw, show_hidden=show_hidden, roots=roots)
        case "read":
            max_chars = int(checked.get("max_chars", 2097152))
            result = read(path_raw, max_chars=max_chars, roots=roots)
        case "write":
            append = bool(checked.get("append", False))
            result = write(path_raw, content, append=append, roots=roots)
        case "create_file":
            result = create_file(path_raw, content, roots=roots)
        case "create_folder" | "create_directory" | "mkdir":
            result = create_directory(path_raw, roots=roots)
        case "delete":
            recursive = bool(checked.get("recursive", False))
            result = trash(path_raw, roots=roots)  # Legacy: delete → trash
        case "move":
            result = filesystem_operation("move", path=path_raw, destination=dest, roots=roots)
        case "copy":
            result = filesystem_operation("copy", path=path_raw, destination=dest, roots=roots)
        case "rename":
            result = rename(path_raw, new_name, roots=roots)
        case "find" | "search":
            extension = str(checked.get("extension", ""))
            max_results = int(checked.get("max_results", 100))
            name_pattern = str(checked.get("name_pattern") or name)
            result = search(
                path_raw, name_pattern=name_pattern, extension=extension,
                max_results=max_results, roots=roots,
            )
        case "info" | "metadata":
            result = metadata(path_raw, roots=roots)
        case "disk_usage":
            result = disk_usage(path_raw, roots=roots)
        case "organize_desktop":
            result = organize_desktop(roots=roots)
        case "largest":
            count = int(checked.get("count", 10))
            result = filesystem_operation("largest", path=path_raw, count=count, roots=roots)
        case "undo":
            return "Undo is deprecated. Use trash action instead."
        case _:
            return f"Unknown action: '{action}'"

    return result.message or str(result.data)


def file_controller(
    parameters: dict | None = None,
    response=None,
    player=None,
    session_memory=None,
    *,
    allowlist: Sequence[str | Path] | None = None,
    confirmer: Confirmer | None = None,
    trash: TrashHook | None = None,
    logger: Logger | None = None,
    source: str = "user",
    intent: str = "",
    undo_stack: list[dict[str, Path]] | None = None,
) -> str:
    """Executor entry. Tests inject allowlist, confirmer, trash, and logger."""
    del response, session_memory
    hooks = _Hooks(
        allowlist=_sanitize_allowlist(allowlist),
        confirmer=confirmer,
        trash=trash,
        logger=logger,
        undo_stack=undo_stack if undo_stack is not None else [],
        player=player,
        source=source,
        intent=intent,
    )
    try:
        checked = validate_args(_TOOL, parameters or {})
        decision = authorize(_TOOL, checked, source=hooks.source, intent=hooks.intent)
    except ArgValidationError as exc:
        return f"Invalid arguments: {exc}"

    if decision.kind == DecisionKind.DENY:
        return decision.reason or "Action denied."

    if decision.kind in _NEEDS_CONFIRM:
        if hooks.confirmer is None:
            return "Confirmation is required."
        if not hooks.confirmer(decision):
            return "Confirmation declined."

    try:
        return _run_action(checked, hooks)
    except Exception as exc:
        return f"File controller error: {exc}"


# ---------------------------------------------------------------------------
# Convenience wrappers (for backward compat)
# ---------------------------------------------------------------------------


def list_files(path: str = "desktop", show_hidden: bool = False, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "list", "path": path, "show_hidden": show_hidden},
        **hooks,
    )


def create_file(path: str, content: str = "", **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "create_file", "path": path, "content": content},
        **hooks,
    )


def create_folder(path: str, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "create_folder", "path": path}, **hooks
    )


def delete_file(path: str, confirm: bool = True, **hooks: Any) -> str:
    del confirm
    return file_controller(parameters={"action": "delete", "path": path}, **hooks)


def move_file(source: str, destination: str, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "move", "path": source, "destination": destination},
        **hooks,
    )


def copy_file(source: str, destination: str, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "copy", "path": source, "destination": destination},
        **hooks,
    )


def rename_file(path: str, new_name: str, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "rename", "path": path, "new_name": new_name},
        **hooks,
    )


def read_file(path: str, max_chars: int = 3000, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "read", "path": path, "max_chars": max_chars},
        **hooks,
    )


def write_file(path: str, content: str, append: bool = False, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "write", "path": path, "content": content, "append": append},
        **hooks,
    )


def find_files(
    name: str = "",
    extension: str = "",
    path: str = "desktop",
    max_results: int = 20,
    **hooks: Any,
) -> str:
    return file_controller(
        parameters={
            "action": "find",
            "name": name,
            "extension": extension,
            "path": path,
            "max_results": max_results,
        },
        **hooks,
    )


def get_largest_files(path: str = "desktop", count: int = 10, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "largest", "path": path, "count": count}, **hooks
    )


def get_disk_usage(path: str = "desktop", **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "disk_usage", "path": path}, **hooks
    )


def organize_desktop(**hooks: Any) -> str:
    return file_controller(
        parameters={"action": "organize_desktop"}, **hooks
    )


def get_file_info(path: str, **hooks: Any) -> str:
    return file_controller(
        parameters={"action": "info", "path": path}, **hooks
    )
