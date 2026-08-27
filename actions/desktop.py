"""Closed set of typed desktop operations. No exec sandbox."""

from __future__ import annotationsfrom i18n import t


import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mark.safety import authorize, check_url, validate_args
from mark.safety.errors import ArgValidationError
from mark.safety.types import DecisionKind, SafetyDecision, UntrustedSource

TOOL_NAME = "desktop_control"

READ_OPS = frozenset({"list", "stats", "screen.capture"})
MUTATING_OPS = frozenset(
    {
        "mouse.click",
        "keyboard.type",
        "keyboard.shortcut",
        "window.activate",
        "file.copy",
    }
)
KNOWN_OPS = READ_OPS | MUTATING_OPS

_OS = platform.system()


class UnknownDesktopOpError(ArgValidationError):
    """The requested desktop op is outside the closed set. Never executes."""

    def __init__(self, op: str = "") -> None:
        self.op = op
        super().__init__(TOOL_NAME, "Unknown desktop operation.", field="op")


class DesktopDeniedError(Exception):
    """``authorize`` refused the op, or the confirmer rejected it."""

    def __init__(self, decision: SafetyDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason or "Desktop operation denied.")


@dataclass(frozen=True)
class DesktopBackends:
    """Injected mouse/keyboard/window/screen/copy backends."""

    mouse: Any = None
    keyboard: Any = None
    window: Any = None
    screen: Any = None
    copy: Any = None


def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg:
            path = Path(xdg)
            if path.exists():
                return path
    return Path.home() / "Desktop"


def _resolve_op(params: dict[str, Any]) -> str:
    for key in ("op", "action"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _int_arg(params: dict[str, Any], name: str) -> int:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArgValidationError(
            TOOL_NAME,
            f"Argument '{name}' has the wrong type.",
            field=name,
        )
    return int(value)


def _str_arg(params: dict[str, Any], name: str, *, required: bool = True) -> str:
    value = params.get(name, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ArgValidationError(
            TOOL_NAME,
            f"Argument '{name}' has the wrong type.",
            field=name,
        )
    if required and not value.strip():
        raise ArgValidationError(
            TOOL_NAME,
            f"Missing required argument '{name}'.",
            field=name,
        )
    return value


def _copy_paths(params: dict[str, Any]) -> tuple[str, str]:
    src = params.get("src")
    if not isinstance(src, str) or not src.strip():
        src = params.get("path")
    if not isinstance(src, str) or not src.strip():
        src = params.get("source")
    dest = params.get("destination")
    if not isinstance(dest, str) or not dest.strip():
        dest = params.get("dest")
    if not isinstance(dest, str) or not dest.strip():
        dest = params.get("to")
    if not isinstance(src, str) or not src.strip():
        raise ArgValidationError(
            TOOL_NAME,
            "Missing required argument 'src'.",
            field="src",
        )
    if not isinstance(dest, str) or not dest.strip():
        raise ArgValidationError(
            TOOL_NAME,
            "Missing required argument 'destination'.",
            field="destination",
        )
    return src.strip(), dest.strip()


def _shortcut_keys(params: dict[str, Any]) -> str | list[str]:
    keys = params.get("keys", params.get("shortcut", ""))
    if isinstance(keys, list):
        if not keys or not all(isinstance(item, str) and item.strip() for item in keys):
            raise ArgValidationError(
                TOOL_NAME,
                "Argument 'keys' has the wrong type.",
                field="keys",
            )
        return [item.strip() for item in keys]
    if not isinstance(keys, str) or not keys.strip():
        raise ArgValidationError(
            TOOL_NAME,
            "Missing required argument 'keys'.",
            field="keys",
        )
    return keys.strip()


def _safe_window_title(title: str) -> str:
    cleaned = title.strip()
    if any(char in cleaned for char in ('"', "'", "\n", "\r", "\\")):
        raise ArgValidationError(
            TOOL_NAME,
            "Window title contains unsafe characters.",
            field="title",
        )
    return cleaned


def _load_pyautogui() -> Any:
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError("Desktop automation backend is unavailable.") from exc
    return pyautogui


def _default_mouse_click(x: int, y: int, button: str = "left") -> str:
    pyautogui = _load_pyautogui()
    pyautogui.click(x=x, y=y, button=button)
    return f"Clicked {button} at ({x}, {y})."


def _default_keyboard_type(text: str) -> str:
    pyautogui = _load_pyautogui()
    pyautogui.typewrite(text)
    return "Текст введён."


def _default_keyboard_shortcut(keys: str | list[str]) -> str:
    pyautogui = _load_pyautogui()
    parts = keys.split("+") if isinstance(keys, str) else list(keys)
    parts = [part.strip() for part in parts if part.strip()]
    if not parts:
        raise ArgValidationError(
            TOOL_NAME,
            "Missing required argument 'keys'.",
            field="keys",
        )
    pyautogui.hotkey(*parts)
    return f"Pressed {'+'.join(parts)}."


def _default_window_activate(title: str) -> str:
    safe_title = _safe_window_title(title)
    if _OS == "Darwin":
        import subprocess

        script = (
            f'tell application "System Events" to set frontmost of '
            f'(first process whose name contains "{safe_title}") to true'
        )
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return "Не удалось активировать окно."
        return f"Activated window: {safe_title}"
    pyautogui = _load_pyautogui()
    windows = pyautogui.getWindowsWithTitle(safe_title)
    if not windows:
        return f"Window not found: {safe_title}"
    windows[0].activate()
    return f"Activated window: {safe_title}"


def _default_screen_capture(path: str | None = None) -> str:
    pyautogui = _load_pyautogui()
    dest = Path(path).expanduser() if path else _get_desktop() / "screenshot.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = pyautogui.screenshot()
    image.save(str(dest))
    return f"Captured screen: {dest}"


def _default_file_copy(source: str, destination: str) -> str:
    src = Path(source).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    if not src.exists():
        return f"Source not found: {src.name}"
    if dest.exists():
        return f"Destination already exists: {dest.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return f"Copied {src.name} → {dest}"


def list_desktop(desktop: Path | None = None) -> str:
    root = desktop if desktop is not None else _get_desktop()
    if not root.exists() or not root.is_dir():
        return "Рабочий стол пуст."
    items: list[str] = []
    for item in sorted(root.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count: int | str = len(list(item.iterdir()))
            except PermissionError:
                count = "?"
            items.append(f"📁 {item.name}/ ({count} items)")
        else:
            size = item.stat().st_size
            size_str = (
                f"{size / 1024:.1f} KB"
                if size < 1024 * 1024
                else f"{size / 1024 / 1024:.1f} MB"
            )
            items.append(f"📄 {item.name} ({size_str})")
    if not items:
        return "Рабочий стол пуст."
    return f"Desktop ({len(items)} items):\n" + "\n".join(items)


def get_desktop_stats(desktop: Path | None = None) -> str:
    root = desktop if desktop is not None else _get_desktop()
    if not root.exists() or not root.is_dir():
        return (
            f"Desktop stats ({_OS}):\n"
            f"  Files   : 0\n"
            f"  Folders : 0\n"
            f"  Size    : 0.0 KB\n"
            f"  Path    : {root}"
        )
    files = [item for item in root.iterdir() if item.is_file()]
    folders = [item for item in root.iterdir() if item.is_dir()]
    total_size = sum(item.stat().st_size for item in files if item.exists())
    size_str = (
        f"{total_size / 1024:.1f} KB"
        if total_size < 1024 * 1024
        else f"{total_size / 1024 / 1024:.1f} MB"
    )
    return (
        f"Desktop stats ({_OS}):\n"
        f"  Files   : {len(files)}\n"
        f"  Folders : {len(folders)}\n"
        f"  Size    : {size_str}\n"
        f"  Path    : {root}"
    )


def _call_mouse(backend: Any, params: dict[str, Any]) -> str:
    x = _int_arg(params, "x")
    y = _int_arg(params, "y")
    button = params.get("button", "left")
    if not isinstance(button, str) or not button.strip():
        button = "left"
    if backend is None:
        return _default_mouse_click(x, y, button=button.strip())
    return str(backend.click(x, y, button=button.strip()))


def _call_keyboard_type(backend: Any, params: dict[str, Any]) -> str:
    text = _str_arg(params, "text")
    if backend is None:
        return _default_keyboard_type(text)
    return str(backend.type(text))


def _call_keyboard_shortcut(backend: Any, params: dict[str, Any]) -> str:
    keys = _shortcut_keys(params)
    if backend is None:
        return _default_keyboard_shortcut(keys)
    return str(backend.shortcut(keys))


def _call_window_activate(backend: Any, params: dict[str, Any]) -> str:
    title = _safe_window_title(_str_arg(params, "title"))
    if backend is None:
        return _default_window_activate(title)
    return str(backend.activate(title))


def _call_screen_capture(backend: Any, params: dict[str, Any]) -> str:
    path = params.get("path")
    if path is not None and not isinstance(path, str):
        raise ArgValidationError(
            TOOL_NAME,
            "Argument 'path' has the wrong type.",
            field="path",
        )
    if backend is None:
        return _default_screen_capture(path)
    return str(backend.capture(path))


def _call_file_copy(backend: Any, params: dict[str, Any]) -> str:
    src, dest = _copy_paths(params)
    if backend is None:
        return _default_file_copy(src, dest)
    return str(backend.copy(src, dest))


def _authorize_op(
    params: dict[str, Any],
    op: str,
    *,
    source: UntrustedSource | str,
    intent: str,
    confirmer: Callable[[SafetyDecision], bool] | None,
) -> SafetyDecision:
    auth_args = dict(params)
    auth_args["op"] = op
    auth_args["action"] = op
    decision = authorize(TOOL_NAME, auth_args, source=source, intent=intent)
    if decision.kind == DecisionKind.DENY:
        raise DesktopDeniedError(decision)
    needs_confirm = decision.kind in {
        DecisionKind.CONFIRM,
        DecisionKind.EXACT_CONFIRM,
        DecisionKind.BIOMETRIC,
    }
    if needs_confirm and confirmer is not None and not confirmer(decision):
        raise DesktopDeniedError(decision)
    return decision


def desktop_control(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
    *,
    backends: DesktopBackends | None = None,
    source: UntrustedSource | str = UntrustedSource.USER,
    confirmer: Callable[[SafetyDecision], bool] | None = None,
    desktop_dir: Path | str | None = None,
) -> str:
    """Run one closed desktop op. Executor entry: ``parameters=..., player=None``."""
    del response, session_memory
    params = validate_args(TOOL_NAME, parameters or {})
    op = _resolve_op(params)
    url = params.get("url")
    if isinstance(url, str) and url.strip():
        check_url(url)

    if player:
        player.write_log(f"[desktop] {op or 'none'}")

    if op not in KNOWN_OPS:
        raise UnknownDesktopOpError(op)

    injected = backends or DesktopBackends()
    root = Path(desktop_dir).expanduser() if desktop_dir is not None else None

    if op in MUTATING_OPS:
        _authorize_op(params, op, source=source, intent=op, confirmer=confirmer)

    if op == "mouse.click":
        return _call_mouse(injected.mouse, params)
    if op == "keyboard.type":
        return _call_keyboard_type(injected.keyboard, params)
    if op == "keyboard.shortcut":
        return _call_keyboard_shortcut(injected.keyboard, params)
    if op == "window.activate":
        return _call_window_activate(injected.window, params)
    if op == "screen.capture":
        return _call_screen_capture(injected.screen, params)
    if op == "file.copy":
        return _call_file_copy(injected.copy, params)
    if op == "list":
        return list_desktop(root)
    if op == "stats":
        return get_desktop_stats(root)
    raise UnknownDesktopOpError(op)
