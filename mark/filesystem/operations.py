"""Filesystem operations — read, write, append, create, list, search,
metadata, copy, move, rename, trash/delete, directory operations.

Every operation is guarded by the security policy in ``security.py``.
"""

from __future__ import annotations

import os
import shutil
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mark.filesystem.security import (
    MAX_FILE_SIZE,
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    AllowlistRoots,
    Cancelled,
    PathDenied,
    SizeExceeded,
    SymlinkEscape,
    TraversalDetected,
    _check_cancel,
    _is_forbidden_system_path,
    _safe_relative,
    default_allowlist_roots,
    detect_file_type,
    read_safe,
    validate_path,
    validate_write_size,
)

try:
    import send2trash as _send2trash_mod
except ImportError:
    _send2trash_mod = None

# ---------------------------------------------------------------------------
# Undo entry
# ---------------------------------------------------------------------------


@dataclass
class _UndoEntry:
    action: str
    src: Path
    dst: Path


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class FileSystemResult:
    ok: bool
    code: str
    message: str = ""
    data: Any = None
    warnings: tuple[str, ...] = ()

    @classmethod
    def _ok(cls, message: str = "", data: Any = None) -> "FileSystemResult":
        return cls(ok=True, code="ok", message=message, data=data)

    @classmethod
    def err(cls, code: str, message: str) -> "FileSystemResult":
        return cls(ok=False, code=code, message=message)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _log_message(action: str, *paths: Path, roots: tuple[Path, ...]) -> str:
    parts = [f"[filesystem] {action}"]
    parts.extend(str(p) for p in paths)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read(
    path_raw: str,
    roots: tuple[Path, ...] | None = None,
    max_chars: int = MAX_READ_BYTES,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Read a text file with full security checks."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not target.is_file():
        return FileSystemResult.err("not_a_file", f"Not a file: {target}")

    try:
        file_type = detect_file_type(target)
        if file_type == "binary":
            return FileSystemResult.err(
                "binary_file",
                f"File is binary ({file_type}). Cannot read as text: {target.name}",
            )
        content = read_safe(target, max_chars=max_chars, cancel_event=cancel_event)
        return FileSystemResult._ok(
            message=f"Read {target.name} ({len(content)} chars)",
            data=content,
        )
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied: {target}")
    except Cancelled:
        return FileSystemResult.err("cancelled", "Read operation cancelled.")
    except OSError as exc:
        return FileSystemResult.err("read_error", f"Cannot read {target}: {exc}")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write(
    path_raw: str,
    content: str,
    append: bool = False,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Write (or append) text to a file."""
    _check_cancel(cancel_event)
    try:
        byte_size = validate_write_size(content)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots)
        # Ensure parent exists
        target.parent.mkdir(parents=True, exist_ok=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    mode = "a" if append else "w"
    try:
        target.write_text(content, encoding="utf-8")
        action = "Appended" if append else "Written"
        return FileSystemResult._ok(
            message=f"{action}: {target.name} ({byte_size} bytes)"
        )
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied: {target}")
    except OSError as exc:
        return FileSystemResult.err("write_error", f"Cannot write {target}: {exc}")


# ---------------------------------------------------------------------------
# Create file (truncate / write from scratch)
# ---------------------------------------------------------------------------


def create_file(
    path_raw: str,
    content: str = "",
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Create a new file (or truncate an existing one)."""
    _check_cancel(cancel_event)
    try:
        byte_size = validate_write_size(content)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)

    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots)
        target.parent.mkdir(parents=True, exist_ok=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    try:
        target.write_text(content, encoding="utf-8")
        return FileSystemResult._ok(
            message=f"Created: {target.name} ({byte_size} bytes)"
        )
    except FileExistsError:
        # File exists — this is expected for create semantics; treat as write
        return write(path_raw, content, roots=roots, cancel_event=cancel_event)
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied: {target}")
    except OSError as exc:
        return FileSystemResult.err("create_error", f"Cannot create {target}: {exc}")


# ---------------------------------------------------------------------------
# Create directory
# ---------------------------------------------------------------------------


def create_directory(
    path_raw: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Create a directory (parents included)."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots)
        target.mkdir(parents=True, exist_ok=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if target.is_dir():
        return FileSystemResult._ok(message=f"Directory exists: {target}")
    return FileSystemResult._ok(message=f"Created: {target}")


# ---------------------------------------------------------------------------
# List directory
# ---------------------------------------------------------------------------


def list_directory(
    path_raw: str,
    show_hidden: bool = False,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """List directory contents."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not target.exists():
        return FileSystemResult.err("not_found", f"Not found: {target}")
    if not target.is_dir():
        return FileSystemResult.err("not_a_directory", f"Not a directory: {target}")

    items: list[str] = []
    try:
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Cannot list {target}")
    except OSError as exc:
        return FileSystemResult.err("list_error", f"Cannot list {target}: {exc}")

    if not items:
        return FileSystemResult._ok(message=f"Directory is empty: {target.name}/")
    return FileSystemResult._ok(
        message=f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)
    )


# ---------------------------------------------------------------------------
# Search / find
# ---------------------------------------------------------------------------


def search(
    path_raw: str,
    name_pattern: str = "",
    extension: str = "",
    max_results: int = 100,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Recursively search for files matching a pattern."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        search_path = validate_path(path_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not search_path.exists():
        return FileSystemResult.err("not_found", f"Search path not found: {search_path}")
    if not search_path.is_dir():
        return FileSystemResult.err("not_a_directory", f"Not a directory: {search_path}")

    results: list[str] = []
    pattern = f"*{extension}" if extension else "*"

    try:
        for item in search_path.rglob(pattern):
            _check_cancel(cancel_event)
            if not item.is_file():
                continue
            resolved = item.resolve()
            # Re-validate inside allowlist
            if not any(_safe_relative(resolved, r) is not None for r in roots):
                continue
            if _is_forbidden_system_path(resolved):
                continue
            if name_pattern and name_pattern.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break
    except PermissionError:
        pass  # Continue on permission errors
    except OSError:
        pass  # Continue on OS errors

    query = name_pattern or extension or "files"
    if not results:
        return FileSystemResult._ok(message=f"No {query} found in {search_path.name}/")
    return FileSystemResult._ok(
        message=f"Found {len(results)} file(s):\n" + "\n".join(results)
    )



# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def metadata(
    path_raw: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Get file/directory metadata."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not target.exists():
        return FileSystemResult.err("not_found", f"Not found: {target}")

    try:
        stat = target.stat()
        info = {
            "name": target.name,
            "type": "directory" if target.is_dir() else "file",
            "size": stat.st_size,
            "size_formatted": _format_size(stat.st_size),
            "location": str(target.parent),
            "extension": target.suffix or "",
            "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "file_type": detect_file_type(target),
        }
        return FileSystemResult._ok(message=f"Metadata for {target.name}", data=info)
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied: {target}")
    except OSError as exc:
        return FileSystemResult.err("metadata_error", f"Cannot get metadata: {exc}")


# ---------------------------------------------------------------------------
# Disk usage
# ---------------------------------------------------------------------------


def disk_usage(
    path_raw: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Get disk usage for a mount point."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    try:
        usage = shutil.disk_usage(target)
        return FileSystemResult._ok(
            message=(
                f"Disk usage for {target}:\n"
                f"  Total : {_format_size(usage.total)}\n"
                f"  Used  : {_format_size(usage.used)} ({usage.used / usage.total * 100:.1f}%)\n"
                f"  Free  : {_format_size(usage.free)}"
            )
        )
    except OSError as exc:
        return FileSystemResult.err("disk_usage_error", f"Cannot read disk usage: {exc}")


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


def copy(
    source_raw: str,
    dest_raw: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Copy a file or directory."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        src = validate_path(source_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("source_path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    try:
        dest = validate_path(dest_raw, roots)
        if dest.exists() and dest.is_dir():
            dest = (dest / src.name).resolve()
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("dest_path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not src.exists():
        return FileSystemResult.err("source_not_found", f"Source not found: {src}")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dest))
        else:
            shutil.copy2(str(src), str(dest))
        return FileSystemResult._ok(message=f"Copied: {src.name} → {dest.parent.name}/")
    except FileExistsError:
        return FileSystemResult.err("exists", f"Destination exists: {dest}")
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied.")
    except OSError as exc:
        return FileSystemResult.err("copy_error", f"Cannot copy: {exc}")


# ---------------------------------------------------------------------------
# Move / rename
# ---------------------------------------------------------------------------


def move(
    source_raw: str,
    dest_raw: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Move a file or directory."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        src = validate_path(source_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("source_path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    try:
        dest = validate_path(dest_raw, roots)
        if dest.exists() and dest.is_dir():
            dest = (dest / src.name).resolve()
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("dest_path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not src.exists():
        return FileSystemResult.err("source_not_found", f"Source not found: {src}")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return FileSystemResult._ok(message=f"Moved: {src.name} → {dest.parent.name}/")
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied.")
    except OSError as exc:
        return FileSystemResult.err("move_error", f"Cannot move: {exc}")


def rename(
    path_raw: str,
    new_name: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Rename a file or directory."""
    _check_cancel(cancel_event)
    if not new_name or not new_name.strip():
        return FileSystemResult.err("missing_field", "new_name is required.")

    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    new_path = (target.parent / new_name).resolve()
    # Validate the new path is also in allowlist
    if not any(_safe_relative(new_path, r) is not None for r in roots):
        return FileSystemResult.err("path_denied", "New path is outside the allowlist.")
    if _is_forbidden_system_path(new_path):
        return FileSystemResult.err("path_denied", "New path is a system path.")

    if not target.exists():
        return FileSystemResult.err("not_found", f"Not found: {target}")
    if new_path.exists():
        return FileSystemResult.err("exists", f"A file named '{new_name}' already exists.")

    try:
        target.rename(new_path)
        return FileSystemResult._ok(message=f"Renamed: {target.name} → {new_name}")
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied.")
    except OSError as exc:
        return FileSystemResult.err("rename_error", f"Cannot rename: {exc}")


# ---------------------------------------------------------------------------
# Trash / Delete
# ---------------------------------------------------------------------------


def trash(
    path_raw: str,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Move a file or directory to the system trash/recycle bin."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not target.exists():
        return FileSystemResult.err("not_found", f"Not found: {target}")

    if _send2trash_mod is None:
        return FileSystemResult.err(
            "trash_unavailable",
            "Trash is unavailable. Install send2trash package.",
        )

    try:
        _send2trash_mod.send2trash(str(target))
        return FileSystemResult._ok(message=f"Moved to Recycle Bin: {target.name}")
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied.")
    except OSError as exc:
        return FileSystemResult.err("trash_error", f"Cannot trash {target}: {exc}")


def delete(
    path_raw: str,
    recursive: bool = False,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Permanently delete a file or directory (irreversible)."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        target = validate_path(path_raw, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not target.exists():
        return FileSystemResult.err("not_found", f"Not found: {target}")

    try:
        if target.is_dir() and recursive:
            shutil.rmtree(str(target))
        elif target.is_dir():
            return FileSystemResult.err(
                "directory_requires_recursive",
                f"{target} is a directory. Use recursive=True to delete.",
            )
        else:
            target.unlink()
        return FileSystemResult._ok(message=f"Permanently deleted: {target.name}")
    except PermissionError:
        return FileSystemResult.err("permission_denied", f"Permission denied.")
    except OSError as exc:
        return FileSystemResult.err("delete_error", f"Cannot delete {target}: {exc}")


# ---------------------------------------------------------------------------
# Organize (desktop)
# ---------------------------------------------------------------------------


def organize_desktop(
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
) -> FileSystemResult:
    """Organize desktop files into subfolders by extension."""
    _check_cancel(cancel_event)
    try:
        roots = roots or default_allowlist_roots()
        desktop = validate_path("desktop", roots)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not desktop.exists() or not desktop.is_dir():
        return FileSystemResult.err("not_found", f"Desktop not found: {desktop}")

    type_map = {
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico"],
        "Documents": [".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"],
        "Videos": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"],
        "Music": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma"],
        "Archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
        "Code": [".py", ".js", ".html", ".css", ".json", ".xml", ".ts", ".cpp", ".java"],
    }

    moved: list[str] = []
    skipped: list[str] = []

    try:
        for item in list(desktop.iterdir()):
            _check_cancel(cancel_event)
            if item.is_dir() or item.name.startswith("."):
                continue
            ext = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, extensions in type_map.items():
                if ext in extensions:
                    target_dir = desktop / folder
                    break
            new_path = (target_dir / item.name).resolve()
            if not any(_safe_relative(new_path, r) is not None for r in roots):
                skipped.append(item.name)
                continue
            if new_path.exists():
                skipped.append(item.name)
                continue
            target_dir.mkdir(exist_ok=True)
            shutil.move(str(item), str(new_path))
            moved.append(f"{item.name} → {target_dir.name}/")
    except OSError:
        pass

    result = f"Desktop organized. {len(moved)} files moved."
    if moved:
        result += "\n" + "\n".join(moved[:10])
        if len(moved) > 10:
            result += f"\n... and {len(moved) - 10} more."
    if skipped:
        result += f"\n{len(skipped)} files skipped (already exist)."
    return FileSystemResult._ok(message=result)


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def filesystem_operation(
    action: str,
    *,
    path: str = "",
    path_raw: str = "",
    content: str = "",
    destination: str = "",
    name: str = "",
    new_name: str = "",
    show_hidden: bool = False,
    extension: str = "",
    name_pattern: str = "",
    max_chars: int = MAX_READ_BYTES,
    max_results: int = 100,
    append: bool = False,
    recursive: bool = False,
    count: int = 10,
    roots: tuple[Path, ...] | None = None,
    cancel_event: threading.Event | None = None,
    **_extra: Any,
) -> FileSystemResult:
    """Single dispatcher for all filesystem operations."""
    _check_cancel(cancel_event)

    # Resolve path argument (path or path_raw)
    target_path = path or path_raw

    match action.lower().strip():
        case "read":
            return read(target_path, roots=roots, max_chars=max_chars, cancel_event=cancel_event)
        case "write":
            return write(target_path, content, append=append, roots=roots, cancel_event=cancel_event)
        case "create_file" | "create":
            return create_file(target_path, content, roots=roots, cancel_event=cancel_event)
        case "create_directory" | "mkdir" | "create_folder":
            return create_directory(target_path, roots=roots, cancel_event=cancel_event)
        case "list" | "list_directory":
            return list_directory(target_path, show_hidden=show_hidden, roots=roots, cancel_event=cancel_event)
        case "search" | "find":
            return search(
                target_path,
                name_pattern=name_pattern or name,
                extension=extension,
                max_results=max_results,
                roots=roots,
                cancel_event=cancel_event,
            )
        case "metadata" | "info" | "stat":
            return metadata(target_path, roots=roots, cancel_event=cancel_event)
        case "disk_usage":
            return disk_usage(target_path, roots=roots, cancel_event=cancel_event)
        case "copy":
            return copy(target_path, destination, roots=roots, cancel_event=cancel_event)
        case "move" | "rename":
            return rename(target_path, new_name or destination, roots=roots, cancel_event=cancel_event)
        case "delete" | "trash" | "remove":
            if action == "trash" or action == "remove":
                return trash(target_path, roots=roots, cancel_event=cancel_event)
            return delete(target_path, recursive=recursive, roots=roots, cancel_event=cancel_event)
        case "organize_desktop":
            return organize_desktop(roots=roots, cancel_event=cancel_event)
        case "largest":
            # Largest files in a directory
            return _do_largest(target_path, count, roots, cancel_event)
        case "undo":
            return FileSystemResult.err("deprecated", "Undo is deprecated; use trash.")
        case _:
            return FileSystemResult.err("unknown_action", f"Unknown action: {action}")


def _do_largest(
    search_path: str,
    count: int,
    roots: tuple[Path, ...] | None,
    cancel_event: threading.Event | None,
) -> FileSystemResult:
    """Get the largest files in a directory."""
    try:
        roots = roots or default_allowlist_roots()
        base = validate_path(search_path, roots, check_size=True)
    except (PathDenied, TraversalDetected) as exc:
        return FileSystemResult.err("path_denied", exc.message)
    except SizeExceeded as exc:
        return FileSystemResult.err("size_exceeded", exc.message)
    except Cancelled:
        return FileSystemResult.err("cancelled", "Operation cancelled.")

    if not base.exists():
        return FileSystemResult.err("not_found", f"Path not found: {base}")
    if not base.is_dir():
        return FileSystemResult.err("not_a_directory", f"Not a directory: {base}")

    files: list[tuple[int, Path]] = []
    try:
        for item in base.rglob("*"):
            _check_cancel(cancel_event)
            if not item.is_file():
                continue
            resolved = item.resolve()
            if not any(_safe_relative(resolved, r) is not None for r in roots):
                continue
            if _is_forbidden_system_path(resolved):
                continue
            try:
                files.append((item.stat().st_size, item))
            except OSError:
                continue
    except OSError:
        pass

    files.sort(reverse=True)
    top = files[:count]
    if not top:
        return FileSystemResult._ok(message="Файлы не найдены.")
    lines = [f"Top {len(top)} largest files in {base.name}/:\n"]
    for size, path in top:
        lines.append(f"  {_format_size(size):>10}  {path.name}  ({path.parent})")
    return FileSystemResult._ok(message="\n".join(lines))


__all__ = [
    "FileSystemResult",
    "filesystem_operation",
    # Individual operations
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
