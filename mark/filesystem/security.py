"""Canonical filesystem security policy.

This module is the single source of truth for every filesystem operation.
It enforces:

* Canonical allowlisted roots (user folders only).
* Absolute path resolution with ``os.path.realpath`` / ``Path.resolve()``.
* Directory-traversal protection (``..`` escaping).
* Symlink-escape protection (every component must stay within roots).
* System-directory denial (/etc, /usr, /proc, …).
* Size limits for reads and writes.
* UTF-8 encoding with fallback.
* Binary / text distinction.
* Cancellation via ``threading.Event``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# System paths that are always forbidden regardless of allowlist membership.
# ---------------------------------------------------------------------------

_FORBIDDEN_POSIX: frozenset[str] = frozenset({
    "/", "/etc", "/system", "/usr", "/bin", "/sbin",
    "/var", "/dev", "/proc", "/root", "/boot",
    "/lib", "/lib64", "/private/etc",
})

_FORBIDDEN_WINDOWS: frozenset[str] = frozenset({
    "c:", "c:/", "c:/windows", "c:/windows/system32",
    "c:/program files", "c:/program files (x80)",
    "c:/programdata",
})

# ---------------------------------------------------------------------------
# Size limits (bytes)
# ---------------------------------------------------------------------------

MAX_READ_BYTES: int = 2 * 1024 * 1024          # 2 MB read ceiling
MAX_WRITE_BYTES: int = 2 * 1024 * 1024        # 2 MB write ceiling
MAX_FILE_SIZE: int = 100 * 1024 * 1024        # 100 MB file size ceiling

# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

_DEFAULT_ENCODING = "utf-8"
_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".xml", ".html", ".css", ".csv", ".sh", ".bash",
    ".sql", ".rs", ".go", ".java", ".c", ".cpp", ".h",
    ".rb", ".pl", ".php", ".swift", ".kt", ".scala",
    ".rst", ".tex", ".log", ".toml", ".env", ".gitignore",
    ".dockerignore", ".editorconfig", ".gitattributes",
})

_BINARY_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"RIFF", "webm/avi"),
    (b"PK\x03\x04", "zip"),
]

# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class Cancelled(Exception):
    """Raised when an operation is cancelled."""
    pass


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled("Operation cancelled.")


# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------


class PathDenied(Exception):
    """Raised when a path fails security checks."""

    def __init__(self, message: str = "Path is not allowed.") -> None:
        self.message = message
        super().__init__(message)


class SizeExceeded(Exception):
    """Raised when a size limit is exceeded."""

    def __init__(self, message: str = "Size limit exceeded.") -> None:
        self.message = message
        super().__init__(message)


class SymlinkEscape(Exception):
    """Raised when a symlink escapes the allowlist."""

    def __init__(self, message: str = "Symlink escapes allowlist.") -> None:
        self.message = message
        super().__init__(message)


class TraversalDetected(Exception):
    """Raised when directory traversal is detected."""

    def __init__(self, message: str = "Path traversal detected.") -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class AllowlistRoots:
    """Canonical allowlisted roots."""
    roots: tuple[Path, ...]

    def contains(self, resolved: Path) -> bool:
        """Return True if *resolved* is under any root."""
        for root in self.roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False


def _normalize_posix(raw: str) -> str:
    """Normalize a path string for comparison."""
    result = raw.strip().replace("\\", "/").rstrip("/")
    # Preserve root "/" — rstrip('/') would turn "/" into ""
    if result == "" and raw.strip() in ("/", "/ "):
        return "/"
    return result


def _raw_is_forbidden(raw: str) -> bool:
    """Check against the global forbidden list."""
    norm = _normalize_posix(raw)
    if norm == "":
        return False  # Empty string → check resolved path instead
    norm_lower = norm.lower()
    return norm_lower in {p.lower() for p in _FORBIDDEN_POSIX} or norm_lower in {
        w.lower().replace("\\", "/").rstrip("/") for w in _FORBIDDEN_WINDOWS
    }


def _is_forbidden_system_path(path: Path) -> bool:
    """Reject root, home root, and well-known system directories.

    Checks BOTH the raw path and the resolved path against the
    forbidden set. This matters on systems where /bin, /sbin, /lib,
    etc. are symlinks to /usr/... (Debian/Ubuntu merged-usr).
    """
    try:
        resolved = path.resolve()
    except OSError:
        return True

    # Check the raw (unresolved) path first
    raw_as_posix = path.as_posix().lower()
    if raw_as_posix in {p.lower() for p in _FORBIDDEN_POSIX}:
        return True

    # Root parent == self → cannot resolve further → forbidden
    if resolved.parent == resolved:
        return True

    # Entire home directory is forbidden (too broad)
    try:
        home = Path.home().resolve()
        if resolved == home:
            return True
    except OSError:
        pass

    # Check the resolved path
    posix = resolved.as_posix().lower()
    if posix in {p.lower() for p in _FORBIDDEN_POSIX}:
        return True

    win_norm = {w.lower().replace("\\", "/").rstrip("/") for w in _FORBIDDEN_WINDOWS}
    if posix in win_norm:
        return True

    return False


def _has_traversal_component(path_raw: str) -> bool:
    """Detect ``..`` or ``~/.`` components in raw path strings."""
    for part in path_raw.replace("\\", "/").split("/"):
        if part == "..":
            return True
    return False


def _check_symlink_chain(target: Path, roots: tuple[Path, ...]) -> None:
    """Verify that no symlink in the path chain escapes the allowlist."""
    parts = list(target.parts)
    # Reconstruct incrementally and resolve each component
    current = Path(parts[0]) if parts[0] else Path("/")
    for part in parts[1:]:
        current = current / part
        if current.is_symlink():
            real = current.resolve()
            # Check if the symlink target is within any root
            if not any(
                _safe_relative(real, r) is not None for r in roots
            ):
                raise SymlinkEscape(
                    f"Symlink at {current} points outside allowlist ({real})."
                )


def _safe_relative(resolved: Path, root: Path) -> str | None:
    """Return the relative part or None if not under root."""
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None


def validate_path(
    path_raw: str,
    roots: tuple[Path, ...] | Path | str,
    allow_symlinks: bool = False,
    check_size: bool = False,
) -> Path:
    """Resolve and validate a path against the security policy.

    Returns the fully-resolved Path.
    Raises PathDenied, SymlinkEscape, or TraversalDetected on failure.

    Relative paths are resolved relative to the first root so that
    operations like ``write("new.txt", roots=(workspace,))`` work as expected.
    """
    # Normalize roots to tuple[Path, ...]
    if isinstance(roots, str):
        roots = (Path(roots),)
    elif isinstance(roots, Path):
        roots = (roots,)

    if not path_raw or not path_raw.strip():
        return None

    # Check for traversal components before resolution
    if _has_traversal_component(path_raw):
        return None

    try:
        base = Path(path_raw).expanduser()
    except (TypeError, ValueError):
        return None

    # If the path is relative, resolve it relative to the first root.
    # This ensures that "new.txt" with roots=(workspace,) resolves to
    # workspace/new.txt instead of cwd/new.txt.
    if not base.is_absolute():
        if roots:
            base = (roots[0] / path_raw).expanduser()
        # If no roots, let Path.resolve() use cwd (will fail allowlist check)

    # Resolve (handles symlinks, .., .)
    try:
        resolved = base.resolve(strict=False)
    except OSError:
        return None

    # Check for traversal after resolution (edge case with special filesystems)
    if _has_traversal_component(resolved.as_posix()):
        return None

    # System path check (raw + resolved)
    if _is_forbidden_system_path(resolved):
        return None

    # Allowlist check
    if not any(_safe_relative(resolved, r) is not None for r in roots):
        return None

    # Symlink escape check — must check the ORIGINAL path before resolution,
    # because resolve() already follows symlinks and the resolved path no longer
    # contains the symlink component.
    if not allow_symlinks:
        # When symlinks are not allowed, check if any component is a symlink.
        try:
            parts = list(base.parts)
            current = Path(parts[0]) if parts[0] else Path("/")
            for part in parts[1:]:
                current = current / part
                if current.exists() and current.is_symlink():
                    return None  # Block all symlinks when not allowed
        except OSError:
            pass
    else:
        # allow_symlinks is True — only block if the symlink escapes the allowlist.
        try:
            if isinstance(base, Path) and base.exists():
                _check_symlink_chain(base, roots)
        except SymlinkEscape:
            raise
        except OSError:
            pass
        if not base.exists():
            try:
                parts = list(base.parts)
                current = Path(parts[0]) if parts[0] else Path("/")
                for part in parts[1:]:
                    current = current / part
                    if current.exists() and current.is_symlink():
                        real = current.resolve()
                        if not any(
                            _safe_relative(real, r) is not None for r in roots
                        ):
                            raise SymlinkEscape(
                                f"Symlink at {current} points outside allowlist ({real})."
                            )
            except SymlinkEscape:
                raise
            except OSError:
                pass

    # Size check (for existing files)
    if check_size and resolved.is_file():
        try:
            size = resolved.stat().st_size
        except OSError:
            size = 0
        if size > MAX_FILE_SIZE:
            raise SizeExceeded(
                f"File size {size} bytes exceeds limit of {MAX_FILE_SIZE}."
            )

    return resolved


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _is_binary(data: bytes) -> bool:
    """Heuristic: check for NUL bytes or binary magic."""
    if b"\x00" in data:
        return True
    for magic, _ in _BINARY_MAGIC:
        if data[:len(magic)] == magic:
            return True
    return False


def detect_file_type(path: Path) -> str:
    """Return 'binary' or 'text' based on content / extension."""
    if not path.is_file():
        return "unknown"
    # First check extension
    ext = path.suffix.lower()
    if ext in _TEXT_EXTENSIONS:
        return "text"
    if ext in {".bin", ".dat", ".exe", ".dll", ".so", ".dylib", ".o", ".a",
               ".pyc", ".pyo", ".class", ".jar", ".war"}:
        return "binary"
    # Check file content (up to 8192 bytes)
    try:
        sample = path.read_bytes()[:8192]
        return "binary" if _is_binary(sample) else "text"
    except OSError:
        return "unknown"


def read_with_encoding(path: Path, max_bytes: int = MAX_READ_BYTES) -> str:
    """Read file content with encoding fallback."""
    try:
        return path.read_text(encoding=_DEFAULT_ENCODING, errors="strict")
    except UnicodeDecodeError:
        return path.read_text(encoding=_DEFAULT_ENCODING, errors="ignore")


def read_safe(
    path: Path,
    max_chars: int = MAX_READ_BYTES,
    cancel_event: threading.Event | None = None,
) -> str:
    """Safe text read with size and cancellation limits."""
    _check_cancel(cancel_event)
    content = read_with_encoding(path, max_bytes=max_chars)
    if len(content) > max_chars:
        return content[:max_chars] + f"\n\n... (truncated, {len(content)} total chars)"
    return content


# ---------------------------------------------------------------------------
# Write security
# ---------------------------------------------------------------------------


def validate_write_size(content: str) -> int:
    """Return byte size and raise SizeExceeded if over limit."""
    byte_size = len(content.encode(_DEFAULT_ENCODING))
    if byte_size > MAX_WRITE_BYTES:
        raise SizeExceeded(
            f"Write size {byte_size} bytes exceeds limit of {MAX_WRITE_BYTES}."
        )
    return byte_size


# ---------------------------------------------------------------------------
# Default allowlist
# ---------------------------------------------------------------------------


def default_allowlist_roots() -> tuple[Path, ...]:
    """User-folder roots. Home itself is never included."""
    home = Path.home()
    roots: list[Path] = []
    for name in ("Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos"):
        candidate = (home / name).expanduser()
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not _is_forbidden_system_path(resolved):
            roots.append(resolved)
    # Also include cwd if it's a reasonable workspace
    try:
        cwd = Path.cwd().resolve()
        if not _is_forbidden_system_path(cwd) and cwd != home:
            roots.append(cwd)
    except OSError:
        pass
    # Also include /tmp for test and temp usage
    try:
        tmp = Path("/tmp").resolve()
        if not _is_forbidden_system_path(tmp):
            roots.append(tmp)
    except OSError:
        pass
    return tuple(roots)


__all__ = [
    "AllowlistRoots",
    "Cancelled",
    "PathDenied",
    "SizeExceeded",
    "SymlinkEscape",
    "TraversalDetected",
    "MAX_READ_BYTES",
    "MAX_WRITE_BYTES",
    "MAX_FILE_SIZE",
    "_check_cancel",
    "default_allowlist_roots",
    "detect_file_type",
    "read_safe",
    "read_with_encoding",
    "validate_path",
    "validate_write_size",
]
