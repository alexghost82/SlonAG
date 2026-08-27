"""Types, enums, and dataclasses for computer-control actions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any


class MouseClickButton(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class ScrollDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class ComputerControlAction(StrEnum):
    MOUSE_MOVE = "mouse.move"
    MOUSE_CLICK = "mouse.click"
    MOUSE_DOUBLE_CLICK = "mouse.double_click"
    MOUSE_RIGHT_CLICK = "mouse.right_click"
    MOUSE_DRAG = "mouse.drag"
    KEYBOARD_TYPE = "keyboard.type"
    KEYBOARD_HOTKEY = "keyboard.hotkey"
    KEYBOARD_PRESS = "keyboard.press"
    SCROLL = "scroll"
    CLIPBOARD_READ = "clipboard.read"
    CLIPBOARD_WRITE = "clipboard.write"
    SCREENSHOT = "screenshot"
    WINDOW_LIST = "window.list"
    WINDOW_FOCUS = "window.focus"
    WINDOW_MINIMIZE = "window.minimize"
    WINDOW_MAXIMIZE = "window.maximize"
    WINDOW_CLOSE = "window.close"
    WINDOW_GET_INFO = "window.info"
    APP_LAUNCH = "app.launch"
    APP_KILL = "app.kill"
    APP_LIST = "app.list"
    VOLUME_GET = "system.volume.get"
    VOLUME_SET = "system.volume.set"
    BRIGHTNESS_GET = "system.brightness.get"
    BRIGHTNESS_SET = "system.brightness.set"
    WAIT = "utility.wait"
    CAPABILITY_CHECK = "capability.check"


class OSPlatform(StrEnum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


class Permission(StrEnum):
    INPUT = "input"
    SCREENSHOT = "screenshot"
    WINDOW_MANAGEMENT = "window_management"
    CLIPBOARD = "clipboard"
    SYSTEM_SETTINGS = "system_settings"
    APP_LAUNCH = "app_launch"


@dataclass(frozen=True)
class ScreenPosition:
    width: int
    height: int
    dpi: float = 96.0
    active_display: int = 0


@dataclass(frozen=True)
class WindowInfo:
    title: str
    pid: int = 0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    is_minimized: bool = False
    is_maximized: bool = False
    is_active: bool = False


@dataclass(frozen=True)
class AppInfo:
    name: str
    pid: int = 0
    path: str = ""
    is_active: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    code: str
    message: str = ""
    data: Any = None
    warnings: tuple[str, ...] = ()
    cancelled: bool = False

    @staticmethod
    def ok_result(message: str = "", data: Any = None, warnings: tuple[str, ...] = ()) -> "ExecutionResult":
        return ExecutionResult(ok=True, code="ok", message=message, data=data, warnings=warnings)

    @staticmethod
    def error_result(code: str, message: str) -> "ExecutionResult":
        return ExecutionResult(ok=False, code=code, message=message)

    @staticmethod
    def cancelled_result() -> "ExecutionResult":
        return ExecutionResult(ok=False, code="cancelled", message="Action was cancelled.", cancelled=True)


@dataclass(frozen=True)
class CancellationToken:
    _cancelled: bool = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        if self._cancelled:
            raise asyncio.CancelledError("Computer control action was cancelled.")


# Action -> required fields mapping for validation
ACTION_FIELDS: dict[ComputerControlAction, tuple[str, ...]] = {
    ComputerControlAction.MOUSE_MOVE: ("x", "y"),
    ComputerControlAction.MOUSE_CLICK: (),
    ComputerControlAction.MOUSE_DOUBLE_CLICK: (),
    ComputerControlAction.MOUSE_RIGHT_CLICK: (),
    ComputerControlAction.MOUSE_DRAG: ("x1", "y1", "x2", "y2"),
    ComputerControlAction.KEYBOARD_TYPE: ("text",),
    ComputerControlAction.KEYBOARD_HOTKEY: ("keys",),
    ComputerControlAction.KEYBOARD_PRESS: ("key",),
    ComputerControlAction.SCROLL: (),
    ComputerControlAction.CLIPBOARD_READ: (),
    ComputerControlAction.CLIPBOARD_WRITE: ("text",),
    ComputerControlAction.SCREENSHOT: (),
    ComputerControlAction.WINDOW_LIST: (),
    ComputerControlAction.WINDOW_FOCUS: ("title",),
    ComputerControlAction.WINDOW_MINIMIZE: ("title",),
    ComputerControlAction.WINDOW_MAXIMIZE: ("title",),
    ComputerControlAction.WINDOW_CLOSE: ("title",),
    ComputerControlAction.WINDOW_GET_INFO: ("title",),
    ComputerControlAction.APP_LAUNCH: ("path", "name"),
    ComputerControlAction.APP_KILL: ("pid", "name"),
    ComputerControlAction.APP_LIST: (),
    ComputerControlAction.VOLUME_GET: (),
    ComputerControlAction.VOLUME_SET: ("value",),
    ComputerControlAction.BRIGHTNESS_GET: (),
    ComputerControlAction.BRIGHTNESS_SET: ("value",),
    ComputerControlAction.WAIT: ("seconds",),
    ComputerControlAction.CAPABILITY_CHECK: (),
}


__all__ = [
    "MouseClickButton",
    "ScrollDirection",
    "ComputerControlAction",
    "OSPlatform",
    "Permission",
    "ScreenPosition",
    "WindowInfo",
    "AppInfo",
    "ExecutionResult",
    "CancellationToken",
    "ACTION_FIELDS",
]
