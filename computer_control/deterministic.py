"""Deterministic (mock) platform adapter for E2E testing.

This adapter NEVER touches the real desktop. Every action produces
structured, repeatable results with a full call log. Use it for CI,
automated tests, and safe development.
"""

from __future__ import annotations

from typing import Any

from computer_control.platform import PlatformAdapter
from computer_control.types import (
    ACTION_FIELDS,
    AppInfo,
    CancellationToken,
    ExecutionResult,
    MouseClickButton,
    OSPlatform,
    ScrollDirection,
    ScreenPosition,
    WindowInfo,
)


class MockPlatformAdapter(PlatformAdapter):
    """Deterministic platform adapter for E2E testing.

    Does NOT touch the real desktop. All actions produce
    structured mock results. Ideal for CI and automated tests.
    """

    def __init__(self) -> None:
        self._log: list[dict[str, Any]] = []
        self._clipboard: str = ""
        self._volume: int = 50
        self._brightness: int = 75
        self._window_counter: int = 1000

        # Pre-seeded windows
        self._windows: dict[int, WindowInfo] = {
            self._window_counter + 0: WindowInfo(
                title="SlonAG - main.py", pid=1001,
                x=0, y=0, width=1920, height=1080, is_active=True,
            ),
            self._window_counter + 1: WindowInfo(
                title="Terminal", pid=1002,
                x=200, y=200, width=800, height=600,
            ),
            self._window_counter + 2: WindowInfo(
                title="Visual Studio Code", pid=1003,
                x=400, y=100, width=1200, height=900,
            ),
        }
        self._window_counter += 3

    def _record(self, action: str, params: dict[str, Any]) -> None:
        self._log.append({"action": action, "params": params})

    @property
    def platform(self) -> OSPlatform:
        return OSPlatform.UNKNOWN  # mock doesn't target a real OS

    @property
    def log(self) -> list[dict[str, Any]]:
        """Return the full call log."""
        return list(self._log)

    def clear_log(self) -> None:
        """Clear the call log."""
        self._log.clear()

    # ── Mouse ──────────────────────────────────────────────────────

    def mouse_move(
        self, x: int, y: int, token: CancellationToken | None = None
    ) -> ExecutionResult:
        if token:
            token.check()
        self._record("mouse_move", {"x": x, "y": y})
        return ExecutionResult.ok_result(
            message=f"Mouse moved to ({x}, {y}) [mock]",
            data={"x": x, "y": y},
        )

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: MouseClickButton = MouseClickButton.LEFT,
        clicks: int = 1,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if token:
            token.check()
        pos = (x, y) if (x is not None and y is not None) else ("current", "current")
        self._record("mouse_click", {"x": pos[0], "y": pos[1], "button": button, "clicks": clicks})
        return ExecutionResult.ok_result(
            message=f"Mouse clicked {clicks}x {button.value} at {pos} [mock]",
            data={"button": button, "clicks": clicks, "x": pos[0], "y": pos[1]},
        )

    def mouse_drag(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.5,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if token:
            token.check()
        self._record("mouse_drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration})
        return ExecutionResult.ok_result(
            message=f"Mouse dragged ({x1},{y1})→({x2},{y2}) [mock]",
            data={"start": (x1, y1), "end": (x2, y2)},
        )

    # ── Keyboard ───────────────────────────────────────────────────

    def keyboard_type(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        self._record("keyboard_type", {"text": text})
        return ExecutionResult.ok_result(
            message=f"Typed {len(text)} chars [mock]",
            data={"text": text, "length": len(text)},
        )

    def keyboard_hotkey(self, keys: list[str], token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        self._record("keyboard_hotkey", {"keys": keys})
        return ExecutionResult.ok_result(
            message=f"Hotkey pressed: {'+'.join(keys)} [mock]",
            data={"keys": keys},
        )

    def keyboard_press(self, key: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        self._record("keyboard_press", {"key": key})
        return ExecutionResult.ok_result(
            message=f"Key pressed: {key} [mock]",
            data={"key": key},
        )

    # ── Scroll ─────────────────────────────────────────────────────

    def scroll(
        self, direction: ScrollDirection, amount: int, token: CancellationToken | None = None
    ) -> ExecutionResult:
        if token:
            token.check()
        self._record("scroll", {"direction": direction, "amount": amount})
        return ExecutionResult.ok_result(
            message=f"Scrolled {amount}x {direction.value} [mock]",
            data={"direction": direction, "amount": amount},
        )

    # ── Clipboard ──────────────────────────────────────────────────

    def clipboard_read(self, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        self._record("clipboard_read", {})
        return ExecutionResult.ok_result(
            message="Clipboard read [mock]",
            data={"text": self._clipboard},
        )

    def clipboard_write(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        self._clipboard = text
        self._record("clipboard_write", {"text_length": len(text)})
        return ExecutionResult.ok_result(
            message=f"Clipboard written ({len(text)} chars) [mock]",
            data={"text": text},
        )

    # ── Screenshot ─────────────────────────────────────────────────

    def screenshot(
        self, save_path: str | None = None, token: CancellationToken | None = None
    ) -> ExecutionResult:
        if token:
            token.check()
        self._record("screenshot", {"path": save_path})
        return ExecutionResult.ok_result(
            message="Screenshot captured [mock]",
            data={"path": save_path or "/tmp/screenshot_mock.png", "width": 1920, "height": 1080},
        )

    # ── Window management ─────────────────────────────────────────

    def _find_window(self, title: str) -> WindowInfo | None:
        """Find window by title substring (case-insensitive substring match."""
        title_lower = title.lower()
        for win in self._windows.values():
            if title_lower in win.title.lower():
                return win
        return None

    def window_list(self) -> ExecutionResult:
        self._record("window_list", {})
        windows = list(self._windows.values())
        return ExecutionResult.ok_result(
            message=f"Found {len(windows)} windows [mock]",
            data={"windows": [w.__dict__ for w in windows]},
        )

    def window_focus(self, title: str) -> ExecutionResult:
        self._record("window_focus", {"title": title})
        win = self._find_window(title)
        if win is None:
            return ExecutionResult.error_result(
                "window_not_found",
                f"Window not found: '{title}' [mock]",
            )
        # Activate it
        for w in self._windows.values():
            w = w._replace(is_active=False)
        self._windows[win] = win._replace(is_active=True)
        return ExecutionResult.ok_result(
            message=f"Focused window: '{title}' [mock]",
            data={"title": win.title},
        )

    def window_minimize(self, title: str) -> ExecutionResult:
        self._record("window_minimize", {"title": title})
        win = self._find_window(title)
        if win is None:
            return ExecutionResult.error_result(
                "window_not_found",
                f"Window not found: '{title}' [mock]",
            )
        self._windows[win] = win._replace(is_minimized=True)
        return ExecutionResult.ok_result(
            message=f"Minimized window: '{title}' [mock]",
        )

    def window_maximize(self, title: str) -> ExecutionResult:
        self._record("window_maximize", {"title": title})
        win = self._find_window(title)
        if win is None:
            return ExecutionResult.error_result(
                "window_not_found",
                f"Window not found: '{title}' [mock]",
            )
        self._windows[win] = win._replace(is_maximized=True)
        return ExecutionResult.ok_result(
            message=f"Maximized window: '{title}' [mock]",
        )

    def window_close(self, title: str) -> ExecutionResult:
        self._record("window_close", {"title": title})
        win = self._find_window(title)
        if win is None:
            return ExecutionResult.error_result(
                "window_not_found",
                f"Window not found: '{title}' [mock]",
            )
        del self._windows[win]
        return ExecutionResult.ok_result(
            message=f"Closed window: '{title}' [mock]",
        )

    def window_get_info(self, title: str) -> ExecutionResult:
        self._record("window_get_info", {"title": title})
        win = self._find_window(title)
        if win is None:
            return ExecutionResult.error_result(
                "window_not_found",
                f"Window not found: '{title}' [mock]",
            )
        return ExecutionResult.ok_result(
            message=f"Window info: '{title}' [mock]",
            data=win.__dict__,
        )

    # ── App management ─────────────────────────────────────────────

    def app_launch(self, path: str = "", name: str = "") -> ExecutionResult:
        self._record("app_launch", {"path": path, "name": name})
        pid = self._window_counter
        self._window_counter += 1
        if name:
            self._windows[pid] = WindowInfo(
                title=name, pid=pid,
                x=0, y=0, width=1024, height=768,
            )
        return ExecutionResult.ok_result(
            message=f"App launched: {name or path or 'unknown'} [mock]",
            data={"pid": pid},
        )

    def app_kill(self, pid: int = 0, name: str = "") -> ExecutionResult:
        self._record("app_kill", {"pid": pid, "name": name})
        # Remove from window list
        to_remove = [wid for wid, w in self._windows.items() if w.pid == pid]
        for wid in to_remove:
            del self._windows[wid]
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

    # ── System settings ────────────────────────────────────────────

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

    # ── Screen info ────────────────────────────────────────────────

    def screen_info(self) -> ExecutionResult:
        self._record("screen_info", {})
        return ExecutionResult.ok_result(
            message="Screen info [mock]",
            data={"width": 1920, "height": 1080, "dpi": 96.0, "active_display": 0},
        )

    def check_permission(self, permission: str) -> ExecutionResult:
        self._record("permission_check", {"permission": permission})
        return ExecutionResult.ok_result(
            message=f"Permission '{permission}' granted [mock]",
            data={"granted": True},
        )
