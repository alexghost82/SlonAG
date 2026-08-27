"""Platform adapter base class and platform-specific adapters."""

from __future__ import annotations

import platform
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from computer_control.types import (
    ACTION_FIELDS,
    AppInfo,
    CancellationToken,
    ComputerControlAction,
    ExecutionResult,
    MouseClickButton,
    OSPlatform,
    ScrollDirection,
    ScreenPosition,
    WindowInfo,
)


class PlatformAdapter(ABC):
    """Base class for platform-specific computer control operations.

    Each action returns an ExecutionResult. Failures return ok=False
    with an honest Russian error message.
    """

    @property
    @abstractmethod
    def platform(self) -> OSPlatform:
        """Return detected OS platform."""

    @abstractmethod
    def mouse_move(self, x: int, y: int, token: CancellationToken | None = None) -> ExecutionResult:
        """Move mouse cursor to (x, y)."""

    @abstractmethod
    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: MouseClickButton = MouseClickButton.LEFT,
        clicks: int = 1,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Click at (x, y) or current position."""

    @abstractmethod
    def mouse_drag(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.5,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Drag from (x1, y1) to (x2, y2)."""

    @abstractmethod
    def keyboard_type(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        """Type text at cursor position."""

    @abstractmethod
    def keyboard_hotkey(self, keys: list[str], token: CancellationToken | None = None) -> ExecutionResult:
        """Press a key combination, e.g. ['ctrl', 'c']."""

    @abstractmethod
    def keyboard_press(self, key: str, token: CancellationToken | None = None) -> ExecutionResult:
        """Press a single key, e.g. 'enter', 'escape'."""

    @abstractmethod
    def scroll(self, direction: ScrollDirection, amount: int, token: CancellationToken | None = None) -> ExecutionResult:
        """Scroll mouse wheel."""

    @abstractmethod
    def clipboard_read(self, token: CancellationToken | None = None) -> ExecutionResult:
        """Read clipboard content."""

    @abstractmethod
    def clipboard_write(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        """Write text to clipboard."""

    @abstractmethod
    def screenshot(self, save_path: str | None = None, token: CancellationToken | None = None) -> ExecutionResult:
        """Capture screen."""

    @abstractmethod
    def window_list(self) -> ExecutionResult:
        """List all visible windows."""

    @abstractmethod
    def window_focus(self, title: str) -> ExecutionResult:
        """Focus a window by title fragment."""

    @abstractmethod
    def window_minimize(self, title: str) -> ExecutionResult:
        """Minimize window by title fragment."""

    @abstractmethod
    def window_maximize(self, title: str) -> ExecutionResult:
        """Maximize window by title fragment."""

    @abstractmethod
    def window_close(self, title: str) -> ExecutionResult:
        """Close window by title fragment."""

    @abstractmethod
    def window_get_info(self, title: str) -> ExecutionResult:
        """Get info about a window by title fragment."""

    @abstractmethod
    def app_launch(self, path: str = "", name: str = "") -> ExecutionResult:
        """Launch application."""

    @abstractmethod
    def app_kill(self, pid: int = 0, name: str = "") -> ExecutionResult:
        """Kill application by PID or name."""

    @abstractmethod
    def app_list(self) -> ExecutionResult:
        """List running applications."""

    @abstractmethod
    def volume_get(self) -> ExecutionResult:
        """Get current volume level."""

    @abstractmethod
    def volume_set(self, value: int) -> ExecutionResult:
        """Set volume level (0-100)."""

    @abstractmethod
    def brightness_get(self) -> ExecutionResult:
        """Get current brightness level."""

    @abstractmethod
    def brightness_set(self, value: int) -> ExecutionResult:
        """Set brightness level (0-100)."""

    @abstractmethod
    def screen_info(self) -> ExecutionResult:
        """Get screen resolution and DPI."""

    @abstractmethod
    def check_permission(self, permission: str) -> ExecutionResult:
        """Check if a permission is granted."""


class MockPlatformAdapter(PlatformAdapter):
    """Deterministic platform adapter for E2E testing.

    Does NOT touch the real desktop. All actions produce
    structured mock results. Ideal for CI and automated tests.
    """

    def __init__(self) -> None:
        self._log: list[dict[str, Any]] = []
        self._clipboard: str = ""
        self._volume: int = 50
        self._brightness: int = 80
        self._windows: list[WindowInfo] = [
            WindowInfo(title="SlonAG — Integration", pid=1001, x=100, y=100, width=800, height=600, is_active=True),
            WindowInfo(title="Terminal", pid=1002, x=0, y=0, width=1024, height=768),
            WindowInfo(title="Visual Studio Code", pid=1003, x=200, y=50, width=900, height=700),
        ]
        self._screenshots: list[str] = []

    @property
    def platform(self) -> OSPlatform:
        return OSPlatform.UNKNOWN

    @property
    def log(self) -> list[dict[str, Any]]:
        return list(self._log)

    def _record(self, action: str, params: dict[str, Any]) -> None:
        self._log.append({
            "action": action,
            "params": params,
            "platform": "mock",
        })

    def mouse_move(self, x: int, y: int, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("mouse_move", {"x": x, "y": y})
        return ExecutionResult.ok_result(
            message=f"Mouse moved to ({x}, {y}) [mock]",
        )

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: MouseClickButton = MouseClickButton.LEFT,
        clicks: int = 1,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("mouse_click", {"x": x, "y": y, "button": button, "clicks": clicks})
        label = "double-click" if clicks == 2 else "right-click" if button == MouseClickButton.RIGHT else "click"
        return ExecutionResult.ok_result(
            message=f"{label} at ({x}, {y}) [{button}] (clicks={clicks}) [mock]",
        )

    def mouse_drag(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.5,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("mouse_drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration})
        return ExecutionResult.ok_result(
            message=f"Dragged from ({x1},{y1}) to ({x2},{y2}) in {duration}s [mock]",
        )

    def keyboard_type(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("keyboard_type", {"text": text})
        return ExecutionResult.ok_result(
            message=f"Typed: {text[:80]}{'…' if len(text) > 80 else ''} [mock]",
        )

    def keyboard_hotkey(self, keys: list[str], token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("keyboard_hotkey", {"keys": keys})
        return ExecutionResult.ok_result(
            message=f"Hotkey pressed: {'+'.join(keys)} [mock]",
        )

    def keyboard_press(self, key: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("keyboard_press", {"key": key})
        return ExecutionResult.ok_result(
            message=f"Key pressed: {key} [mock]",
        )

    def scroll(self, direction: ScrollDirection, amount: int, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("scroll", {"direction": direction, "amount": amount})
        return ExecutionResult.ok_result(
            message=f"Scrolled {direction} x{amount} [mock]",
        )

    def clipboard_read(self, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._record("clipboard_read", {})
        return ExecutionResult.ok_result(
            message="Clipboard read [mock]",
            data={"content": self._clipboard},
        )

    def clipboard_write(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        self._clipboard = text
        self._record("clipboard_write", {"text": text})
        return ExecutionResult.ok_result(
            message=f"Clipboard written: {text[:60]}{'…' if len(text) > 60 else ''} [mock]",
        )

    def screenshot(self, save_path: str | None = None, token: CancellationToken | None = None) -> ExecutionResult:
        if token is not None:
            token.check()
        path = save_path or f"/tmp/slon_screenshot_{len(self._screenshots)}.png"
        self._screenshots.append(path)
        self._record("screenshot", {"path": path})
        return ExecutionResult.ok_result(
            message=f"Screenshot saved: {path} [mock]",
            data={"path": path, "width": 1920, "height": 1080},
        )

    def window_list(self) -> ExecutionResult:
        self._record("window_list", {})
        return ExecutionResult.ok_result(
            message=f"Found {len(self._windows)} windows [mock]",
            data={"windows": [w.model_dump() if hasattr(w, 'model_dump') else w.__dict__ for w in self._windows]},
        )

    def window_focus(self, title: str) -> ExecutionResult:
        self._record("window_focus", {"title": title})
        for w in self._windows:
            if title.lower() in w.title.lower():
                return ExecutionResult.ok_result(
                    message=f"Focused window: {w.title} [mock]",
                    data={"window": w.__dict__},
                )
        return ExecutionResult.error_result(
            "window_not_found",
            f"Window not found: '{title}' [mock]",
        )

    def window_minimize(self, title: str) -> ExecutionResult:
        self._record("window_minimize", {"title": title})
        for w in self._windows:
            if title.lower() in w.title.lower():
                return ExecutionResult.ok_result(
                    message=f"Minimized window: {w.title} [mock]",
                )
        return ExecutionResult.error_result(
            "window_not_found",
            f"Window not found: '{title}' [mock]",
        )

    def window_maximize(self, title: str) -> ExecutionResult:
        self._record("window_maximize", {"title": title})
        for w in self._windows:
            if title.lower() in w.title.lower():
                return ExecutionResult.ok_result(
                    message=f"Maximized window: {w.title} [mock]",
                )
        return ExecutionResult.error_result(
            "window_not_found",
            f"Window not found: '{title}' [mock]",
        )

    def window_close(self, title: str) -> ExecutionResult:
        self._record("window_close", {"title": title})
        for i, w in enumerate(self._windows):
            if title.lower() in w.title.lower():
                removed = self._windows.pop(i)
                return ExecutionResult.ok_result(
                    message=f"Closed window: {removed.title} [mock]",
                )
        return ExecutionResult.error_result(
            "window_not_found",
            f"Window not found: '{title}' [mock]",
        )

    def window_get_info(self, title: str) -> ExecutionResult:
        self._record("window_info", {"title": title})
        for w in self._windows:
            if title.lower() in w.title.lower():
                return ExecutionResult.ok_result(
                    message=f"Window info: {w.title} [mock]",
                    data={"window": w.__dict__},
                )
        return ExecutionResult.error_result(
            "window_not_found",
            f"Window not found: '{title}' [mock]",
        )

    def app_launch(self, path: str = "", name: str = "") -> ExecutionResult:
        self._record("app_launch", {"path": path, "name": name})
        return ExecutionResult.ok_result(
            message=f"App launched: {name or path or 'unknown'} [mock]",
            data={"pid": 9999},
        )

    def app_kill(self, pid: int = 0, name: str = "") -> ExecutionResult:
        self._record("app_kill", {"pid": pid, "name": name})
        return ExecutionResult.ok_result(
            message=f"App killed: pid={pid} name={name or 'unknown'} [mock]",
        )

    def app_list(self) -> ExecutionResult:
        self._record("app_list", {})
        apps = [
            AppInfo(name="SlonAG", pid=1001, is_active=True),
            AppInfo(name="Terminal", pid=1002),
            AppInfo(name="Visual Studio Code", pid=1003),
            AppInfo(name="Firefox", pid=1004),
        ]
        return ExecutionResult.ok_result(
            message=f"Found {len(apps)} apps [mock]",
            data={"apps": [a.__dict__ for a in apps]},
        )

    def volume_get(self) -> ExecutionResult:
        self._record("volume_get", {})
        return ExecutionResult.ok_result(
            message="Volume retrieved [mock]",
            data={"level": self._volume, "muted": False},
        )

    def volume_set(self, value: int) -> ExecutionResult:
        self._volume = max(0, min(100, value))
        self._record("volume_set", {"value": self._volume})
        return ExecutionResult.ok_result(
            message=f"Volume set to {self._volume}% [mock]",
            data={"level": self._volume},
        )

    def brightness_get(self) -> ExecutionResult:
        self._record("brightness_get", {})
        return ExecutionResult.ok_result(
            message="Brightness retrieved [mock]",
            data={"level": self._brightness},
        )

    def brightness_set(self, value: int) -> ExecutionResult:
        self._brightness = max(0, min(100, value))
        self._record("brightness_set", {"value": self._brightness})
        return ExecutionResult.ok_result(
            message=f"Brightness set to {self._brightness}% [mock]",
            data={"level": self._brightness},
        )

    def screen_info(self) -> ExecutionResult:
        self._record("screen_info", {})
        return ExecutionResult.ok_result(
            message="Screen info [mock]",
            data={
                "width": 1920,
                "height": 1080,
                "dpi": 96.0,
                "active_display": 0,
            },
        )

    def check_permission(self, permission: str) -> ExecutionResult:
        self._record("permission_check", {"permission": permission})
        # Mock grants all permissions
        return ExecutionResult.ok_result(
            message=f"Permission '{permission}' granted [mock]",
            data={"granted": True},
        )


# ── Real platform adapter builder ────────────────────────────────────


def build_linux_adapter() -> PlatformAdapter:
    """Build a Linux X11/Wayland adapter using XDoX and pyautogui."""
    try:
        from computer_control._linux import LinuxPlatformAdapter
        return LinuxPlatformAdapter()
    except ImportError as exc:
        raise RuntimeError(f"Linux desktop automation unavailable: {exc}") from exc


def build_macos_adapter() -> PlatformAdapter:
    """Build a macOS adapter using AppleScript and pyautogui."""
    try:
        from computer_control._macos import MacPlatformAdapter
        return MacPlatformAdapter()
    except ImportError as exc:
        raise RuntimeError(f"macOS desktop automation unavailable: {exc}") from exc


def build_windows_adapter() -> PlatformAdapter:
    """Build a Windows adapter using ctypes, pyautogui, and win32con."""
    try:
        from computer_control._windows import WindowsPlatformAdapter
        return WindowsPlatformAdapter()
    except ImportError as exc:
        raise RuntimeError(f"Windows desktop automation unavailable: {exc}") from exc


def build_platform_adapter(mode: str = "mock") -> PlatformAdapter:
    """Select the right platform adapter.

    Args:
        mode: "mock" (default, E2E-safe) or "auto" (detect OS).
    """
    if mode == "mock":
        return MockPlatformAdapter()
    if mode == "auto":
        system = platform.system()
        if system == "Linux":
            return build_linux_adapter()
        if system == "Darwin":
            return build_macos_adapter()
        if system == "Windows":
            return build_windows_adapter()
    # Fallback: mock
    return MockPlatformAdapter()


__all__ = [
    "PlatformAdapter",
    "MockPlatformAdapter",
    "build_linux_adapter",
    "build_macos_adapter",
    "build_windows_adapter",
    "build_platform_adapter",
    "MouseClickButton",
    "ScrollDirection",
]
