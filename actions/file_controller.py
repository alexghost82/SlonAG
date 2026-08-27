# actions/file_controller.py
# File management — allowlisted canonical paths, confirmed mutations, trash-only delete.

from __future__ import annotationsfrom i18n import t


import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

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
_FORBIDDEN_POSIX = frozenset(
    {
        "/",
        "/etc",
        "/system",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/dev",
        "/proc",
        "/root",
        "/boot",
        "/lib",
        "/lib64",
        "/private/etc",
        "/windows",
        "/program files",
        "/program files (x86)",
        "/programdata",
    }
)
_FORBIDDEN_RAW = frozenset(
    {
        "/",
        "/etc",
        "/system",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/dev",
        "/proc",
        "/root",
        "/boot",
        "/lib",
        "/lib64",
        "/private/etc",
        "c:",
        "c:/",
        "c:/windows",
        "c:/windows/system32",
        "c:/program files",
        "c:/program files (x86)",
        "c:/programdata",
    }
)
_SHORTCUTS = {
    "desktop": "Desktop",
    "downloads": "Downloads",
    "documents": "Documents",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
    "home": "",
}

_UNDO_STACK: list[dict[str, Path]] = []


class _PathDenied(Exception):
    def __init__(self, message: str = "Path is not allowed.") -> None:
        self.message = message
        super().__init__(message)


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


def default_allowlist() -> tuple[Path, ...]:
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
    return tuple(roots)


def _normalize_raw(raw: str) -> str:
    text = raw.strip().replace("\\", "/").lower()
    if text in {"/", "c:", "c:/"}:
        return "c:/" if text.startswith("c") else "/"
    return text.rstrip("/")


def _raw_is_forbidden(raw: str) -> bool:
    return _normalize_raw(raw) in _FORBIDDEN_RAW


def _is_forbidden_system_path(path: Path, raw: str | None = None) -> bool:
    """Reject filesystem root, entire home, and well-known system directories."""
    if raw is not None and _raw_is_forbidden(raw):
        return True
    try:
        resolved = path.resolve()
    except OSError:
        return True
    if resolved.parent == resolved:
        return True
    try:
        if resolved == Path.home().resolve():
            return True
    except OSError:
        return True
    posix = resolved.as_posix().lower()
    if posix in _FORBIDDEN_POSIX:
        return True
    if _raw_is_forbidden(posix):
        return True
    return False


def _sanitize_allowlist(roots: Sequence[str | Path] | None) -> tuple[Path, ...]:
    if roots is None:
        return default_allowlist()
    cleaned: list[Path] = []
    for root in roots:
        raw = str(root)
        try:
            resolved = Path(root).expanduser().resolve()
        except OSError:
            continue
        if _is_forbidden_system_path(resolved, raw=raw):
            continue
        cleaned.append(resolved)
    return tuple(cleaned)


def _within_allowlist(resolved: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _expand_shortcut_or_path(raw: str) -> Path:
    text = (raw or "").strip()
    if not text:
        raise _PathDenied("Path is empty.")
    key = text.lower()
    if key == "home":
        return Path.home()
    if key in _SHORTCUTS:
        return Path.home() / _SHORTCUTS[key]
    return Path(text).expanduser()


def _resolve_target(path_raw: str, name: str = "") -> Path:
    base = _expand_shortcut_or_path(path_raw)
    target = base / name if name else base
    return target.expanduser().resolve()


def _assert_allowed(resolved: Path, raw: str, roots: Sequence[Path]) -> Path:
    if _is_forbidden_system_path(resolved, raw=raw):
        raise _PathDenied("Path is not allowed.")
    if not _within_allowlist(resolved, roots):
        raise _PathDenied("Path is outside the allowlist.")
    return resolved


def _allowed_path(path_raw: str, roots: Sequence[Path], name: str = "") -> Path:
    resolved = _resolve_target(path_raw, name)
    combined = f"{path_raw.rstrip('/')}/{name}" if name else path_raw
    return _assert_allowed(resolved, combined, roots)


def _resolve_destination(dest_raw: str, src: Path, roots: Sequence[Path]) -> Path:
    if not (dest_raw or "").strip():
        raise _PathDenied("Destination is empty.")
    dest = _expand_shortcut_or_path(dest_raw).expanduser().resolve()
    if dest.exists() and dest.is_dir():
        dest = (dest / src.name).resolve()
    return _assert_allowed(dest, dest_raw, roots)


def _log(hooks: _Hooks, action: str, *paths: Path) -> None:
    parts = [f"[file] {action}"]
    parts.extend(str(path) for path in paths)
    message = " ".join(parts)
    hooks.logs.append(message)
    if hooks.logger is not None:
        hooks.logger(message)
        return
    writer = getattr(hooks.player, "write_log", None)
    if callable(writer):
        writer(message)


def _default_trash(path: Path) -> None:
    if send2trash_mod is None:
        raise RuntimeError("Trash is unavailable.")
    send2trash_mod.send2trash(str(path))


def _send_to_trash(hooks: _Hooks, target: Path) -> None:
    hook = hooks.trash if hooks.trash is not None else _default_trash
    hook(target)


def _format_size(bytes_size: int) -> str:
    size = float(bytes_size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _push_undo(hooks: _Hooks, action: str, src: Path, dst: Path) -> None:
    hooks.undo_stack.append({"action": action, "src": src, "dst": dst})


def _do_list(target: Path, show_hidden: bool) -> str:
    if not target.exists():
        return f"Path not found: {target}"
    if not target.is_dir():
        return f"Not a directory: {target}"
    items: list[str] = []
    for item in sorted(target.iterdir()):
        if not show_hidden and item.name.startswith("."):
            continue
        if item.is_dir():
            items.append(f"📁 {item.name}/")
        else:
            size = _format_size(item.stat().st_size)
            items.append(f"📄 {item.name} ({size})")
    if not items:
        return f"Directory is empty: {target}"
    return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)


def _do_read(target: Path, max_chars: int) -> str:
    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Not a file: {target}"
    content = target.read_text(encoding="utf-8", errors="ignore")
    if len(content) > max_chars:
        return content[:max_chars] + f"\n\n... (truncated, {len(content)} total chars)"
    return content


def _do_create_file(target: Path, content: str) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"File created: {target.name}"


def _do_create_folder(target: Path) -> str:
    target.mkdir(parents=True, exist_ok=True)
    return f"Folder created: {target}"


def _do_write(target: Path, content: str, append: bool) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with target.open(mode, encoding="utf-8") as handle:
        handle.write(content)
    action = "Appended to" if append else "Written to"
    return f"{action}: {target.name}"


def _do_move(src: Path, dst: Path, hooks: _Hooks) -> str:
    if not src.exists():
        return f"Source not found: {src}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    _push_undo(hooks, "move", src, dst)
    return f"Moved: {src.name} → {dst.parent.name}/"


def _do_copy(src: Path, dst: Path) -> str:
    if not src.exists():
        return f"Source not found: {src}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
    return f"Copied: {src.name} → {dst.parent.name}/"


def _do_rename(target: Path, new_name: str, hooks: _Hooks) -> str:
    if not new_name or not str(new_name).strip():
        return "Новое имя пусто."
    new_path = (target.parent / new_name).resolve()
    _assert_allowed(new_path, new_name, hooks.allowlist)
    if not target.exists():
        return f"Not found: {target}"
    if new_path.exists():
        return f"A file named '{new_name}' already exists."
    target.rename(new_path)
    _push_undo(hooks, "rename", target, new_path)
    return f"Renamed: {target.name} → {new_name}"


def _do_delete(target: Path, hooks: _Hooks) -> str:
    if not target.exists():
        return f"Not found: {target}"
    _send_to_trash(hooks, target)
    return f"Moved to Recycle Bin: {target.name}"


def _do_find(
    search_path: Path,
    name: str,
    extension: str,
    max_results: int,
    roots: Sequence[Path],
) -> str:
    if not search_path.exists():
        return f"Search path not found: {search_path}"
    results: list[str] = []
    pattern = f"*{extension}" if extension else "*"
    for item in search_path.rglob(pattern):
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if not _within_allowlist(resolved, roots):
            continue
        if _is_forbidden_system_path(resolved):
            continue
        if not item.is_file():
            continue
        if name and name.lower() not in item.name.lower():
            continue
        size = _format_size(item.stat().st_size)
        results.append(f"📄 {item.name} ({size}) — {item.parent}")
        if len(results) >= max_results:
            break
    if not results:
        query = name or extension or "files"
        return f"No {query} found in {search_path.name}/"
    return f"Found {len(results)} file(s):\n" + "\n".join(results)


def _do_largest(search_path: Path, count: int, roots: Sequence[Path]) -> str:
    if not search_path.exists():
        return f"Path not found: {search_path}"
    files: list[tuple[int, Path]] = []
    for item in search_path.rglob("*"):
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if not _within_allowlist(resolved, roots) or _is_forbidden_system_path(resolved):
            continue
        if item.is_file():
            try:
                files.append((item.stat().st_size, item))
            except OSError:
                continue
    files.sort(reverse=True)
    top = files[:count]
    if not top:
        return "Файлы не найдены."
    lines = [f"Top {len(top)} largest files in {search_path.name}/:\n"]
    for size, path in top:
        lines.append(f"  {_format_size(size):>10}  {path.name}  ({path.parent})")
    return "\n".join(lines)


def _do_disk_usage(target: Path) -> str:
    usage = shutil.disk_usage(target)
    total = _format_size(usage.total)
    used = _format_size(usage.used)
    free = _format_size(usage.free)
    pct = usage.used / usage.total * 100
    return (
        f"Disk usage for {target}:\n"
        f"  Total : {total}\n"
        f"  Used  : {used} ({pct:.1f}%)\n"
        f"  Free  : {free}"
    )


def _do_info(target: Path) -> str:
    if not target.exists():
        return f"Not found: {target}"
    stat = target.stat()
    info = {
        "Name": target.name,
        "Type": "Folder" if target.is_dir() else "File",
        "Size": _format_size(stat.st_size),
        "Location": str(target.parent),
        "Created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
        "Modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "Extension": target.suffix or "None",
    }
    return "\n".join(f"  {key}: {value}" for key, value in info.items())


def _do_organize_desktop(hooks: _Hooks) -> str:
    desktop = _allowed_path("desktop", hooks.allowlist)
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
    if not desktop.exists() or not desktop.is_dir():
        return f"Path not found: {desktop}"
    for item in desktop.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        ext = item.suffix.lower()
        target_dir = desktop / "Others"
        for folder, extensions in type_map.items():
            if ext in extensions:
                target_dir = desktop / folder
                break
        new_path = (target_dir / item.name).resolve()
        try:
            _assert_allowed(new_path, str(new_path), hooks.allowlist)
        except _PathDenied:
            skipped.append(item.name)
            continue
        target_dir.mkdir(exist_ok=True)
        if new_path.exists():
            skipped.append(item.name)
            continue
        shutil.move(str(item), str(new_path))
        _push_undo(hooks, "move", item.resolve(), new_path)
        moved.append(f"{item.name} → {target_dir.name}/")
    result = f"Desktop organized. {len(moved)} files moved."
    if moved:
        result += "\n" + "\n".join(moved[:10])
        if len(moved) > 10:
            result += f"\n... and {len(moved) - 10} more."
    if skipped:
        result += f"\n{len(skipped)} files skipped (already exist)."
    return result


def _do_undo(hooks: _Hooks) -> str:
    if not hooks.undo_stack:
        return "Нечего отменять."
    entry = hooks.undo_stack[-1]
    src = entry["src"]
    dst = entry["dst"]
    try:
        _assert_allowed(src, str(src), hooks.allowlist)
        _assert_allowed(dst, str(dst), hooks.allowlist)
    except _PathDenied as exc:
        return exc.message
    if not dst.exists():
        return "Отмена невозможна: предыдущий путь недоступен."
    if src.exists():
        return "Отмена невозможна: оригинальный путь занят."
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dst), str(src))
    hooks.undo_stack.pop()
    return f"Undid {entry['action']}: {dst.name} → {src}"


def _as_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _run_action(checked: dict[str, object], hooks: _Hooks) -> str:
    action = _as_str(checked.get("action")).strip().lower()
    path_raw = _as_str(checked.get("path"), "desktop")
    name = _as_str(checked.get("name"))
    content = _as_str(checked.get("content"))

    if action == "undo":
        _log(hooks, action)
        return _do_undo(hooks)

    if action == "organize_desktop":
        desktop = _allowed_path("desktop", hooks.allowlist)
        _log(hooks, action, desktop)
        return _do_organize_desktop(hooks)

    if action in {"list", "find", "largest", "disk_usage"}:
        target = _allowed_path(path_raw, hooks.allowlist)
        _log(hooks, action, target)
        if action == "list":
            return _do_list(target, _as_bool(checked.get("show_hidden")))
        if action == "find":
            return _do_find(
                target,
                name or _as_str(checked.get("name")),
                _as_str(checked.get("extension")),
                _as_int(checked.get("max_results"), 20),
                hooks.allowlist,
            )
        if action == "largest":
            return _do_largest(target, _as_int(checked.get("count"), 10), hooks.allowlist)
        return _do_disk_usage(target)

    target = _allowed_path(path_raw, hooks.allowlist, name)
    extra: list[Path] = []
    dest: Path | None = None
    if action in {"move", "copy"}:
        dest = _resolve_destination(_as_str(checked.get("destination")), target, hooks.allowlist)
        extra.append(dest)
    _log(hooks, action, target, *extra)

    if action == "read":
        return _do_read(target, _as_int(checked.get("max_chars"), 3000))
    if action == "info":
        return _do_info(target)
    if action == "create_file":
        return _do_create_file(target, content)
    if action == "create_folder":
        return _do_create_folder(target)
    if action == "write":
        return _do_write(target, content, _as_bool(checked.get("append")))
    if action == "delete":
        return _do_delete(target, hooks)
    if action == "move" and dest is not None:
        return _do_move(target, dest, hooks)
    if action == "copy" and dest is not None:
        return _do_copy(target, dest)
    if action == "rename":
        return _do_rename(target, _as_str(checked.get("new_name")), hooks)
    return f"Unknown action: '{action}'"


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
        undo_stack=_UNDO_STACK if undo_stack is None else undo_stack,
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
            return "Требуется подтверждение."
        if not hooks.confirmer(decision):
            return "Подтверждение отклонено."

    try:
        return _run_action(checked, hooks)
    except _PathDenied as exc:
        return exc.message
    except RuntimeError as exc:
        return str(exc)
    except PermissionError:
        return "Доступ запрещён."
    except Exception as exc:
        return f"File controller error: {exc}"


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
    return file_controller(parameters={"action": "create_folder", "path": path}, **hooks)


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
        parameters={"action": "largest", "path": path, "count": count},
        **hooks,
    )


def get_disk_usage(path: str = "desktop", **hooks: Any) -> str:
    return file_controller(parameters={"action": "disk_usage", "path": path}, **hooks)


def organize_desktop(**hooks: Any) -> str:
    return file_controller(parameters={"action": "organize_desktop"}, **hooks)


def get_file_info(path: str, **hooks: Any) -> str:
    return file_controller(parameters={"action": "info", "path": path}, **hooks)
