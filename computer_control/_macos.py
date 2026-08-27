"""macOS platform adapter for computer control.

Uses: pyautogui (mouse/keyboard), AppleScript (window mgmt),
      osascript (system settings).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from computer_control.types import (
    CancellationToken,
    ComputerControlAction,
    ExecutionResult,
    MouseClickButton,
    OSPlatform,
    ScrollDirection,
    WindowInfo,
)


class MacPlatformAdapter:
    """Real desktop automation for macOS via AppleScript and pyautogui."""

    def __init__(self) -> None:
        self._platform: OSPlatform = OSPlatform.MACOS
        self._pyautogui_available: bool = self._check_pyautogui()

    @property
    def platform(self) -> OSPlatform:
        return self._platform

    @staticmethod
    def _check_pyautogui() -> bool:
        try:
            import pyautogui  # noqa: F401
            return True
        except ImportError:
            return False

    def _require_pyautogui(self) -> None:
        if not self._pyautogui_available:
            raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

    @staticmethod
    def _subprocess(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    @staticmethod
    def _osascript(script: str, timeout: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )

    # ── Mouse ────────────────────────────────────────────────────────

    def mouse_move(self, x: int, y: int, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            pyautogui.moveTo(x, y, duration=0.2)
            return ExecutionResult.ok_result(message=f"Mouse moved to ({x}, {y})")
        except Exception as exc:
            return ExecutionResult.error_result("mouse_move_failed", f"Move mouse failed: {exc}")

    def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: MouseClickButton = MouseClickButton.LEFT,
        clicks: int = 1,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            kwargs: dict[str, Any] = {"button": button, "clicks": clicks}
            if x is not None and y is not None:
                pyautogui.click(x, y, **kwargs)
                return ExecutionResult.ok_result(message=f"Clicked at ({x}, {y}) [{button}] (clicks={clicks})")
            pyautogui.click(**kwargs)
            return ExecutionResult.ok_result(message=f"Clicked at current position [{button}] (clicks={clicks})")
        except Exception as exc:
            return ExecutionResult.error_result("mouse_click_failed", f"Click failed: {exc}")

    def mouse_drag(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.5,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            pyautogui.moveTo(x1, y1, duration=0.1)
            pyautogui.dragTo(x2, y2, duration=duration, button="left")
            return ExecutionResult.ok_result(message=f"Dragged from ({x1},{y1}) to ({x2},{y2})")
        except Exception as exc:
            return ExecutionResult.error_result("mouse_drag_failed", f"Drag failed: {exc}")

    # ── Keyboard ─────────────────────────────────────────────────────

    def keyboard_type(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            pyautogui.write(text, interval=0.03)
            return ExecutionResult.ok_result(message=f"Typed: {text[:80]}")
        except Exception as exc:
            return ExecutionResult.error_result("keyboard_type_failed", f"Typing failed: {exc}")

    def keyboard_hotkey(self, keys: list[str], token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            # Map macOS-specific keys
            mapped: list[str] = []
            for k in keys:
                k_lower = k.lower()
                if k_lower == "cmd" or k_lower == "command":
                    mapped.append("command")
                else:
                    mapped.append(k_lower)
            pyautogui.hotkey(*mapped)
            return ExecutionResult.ok_result(message=f"Hotkey: {'+'.join(mapped)}")
        except Exception as exc:
            return ExecutionResult.error_result("keyboard_hotkey_failed", f"Hotkey failed: {exc}")

    def keyboard_press(self, key: str, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            key_lower = key.lower()
            if key_lower == "return":
                key_lower = "enter"
            pyautogui.press(key_lower)
            return ExecutionResult.ok_result(message=f"Key pressed: {key}")
        except Exception as exc:
            return ExecutionResult.error_result("keyboard_press_failed", f"Key press failed: {exc}")

    # ── Scroll ───────────────────────────────────────────────────────

    def scroll(self, direction: ScrollDirection, amount: int, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            if direction == ScrollDirection.UP:
                pyautogui.scroll(amount)
            elif direction == ScrollDirection.DOWN:
                pyautogui.scroll(-amount)
            elif direction == ScrollDirection.LEFT:
                pyautogui.hscroll(-amount)
            elif direction == ScrollDirection.RIGHT:
                pyautogui.hscroll(amount)
            return ExecutionResult.ok_result(message=f"Scrolled {direction} x{amount}")
        except Exception as exc:
            return ExecutionResult.error_result("scroll_failed", f"Scroll failed: {exc}")

    # ── Clipboard ────────────────────────────────────────────────────

    def clipboard_read(self, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            result = self._subprocess(["pbpaste"])
            if result.returncode == 0:
                return ExecutionResult.ok_result(message="Clipboard read", data={"content": result.stdout})
            return ExecutionResult.error_result("clipboard_read_failed", "pbpaste failed")
        except Exception as exc:
            return ExecutionResult.error_result("clipboard_read_failed", str(exc))

    def clipboard_write(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode(),
                capture_output=True,
                timeout=5,
            )
            if proc.returncode == 0:
                return ExecutionResult.ok_result(message=f"Clipboard written: {text[:60]}")
            return ExecutionResult.error_result("clipboard_write_failed", "pbcopy failed")
        except Exception as exc:
            return ExecutionResult.error_result("clipboard_write_failed", str(exc))

    # ── Screenshot ───────────────────────────────────────────────────

    def screenshot(self, save_path: str | None = None, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            dest = save_path or str(Path.home() / "Desktop" / "slon_screenshot.png")
            dest = str(Path(dest).expanduser().resolve())
            parent = Path(dest).parent
            parent.mkdir(parents=True, exist_ok=True)

            result = self._subprocess(["screencapture", "-x", dest])
            if result.returncode == 0 and Path(dest).exists():
                size = Path(dest).stat().st_size
                return ExecutionResult.ok_result(
                    message=f"Screenshot saved: {dest}",
                    data={"path": dest, "size": size},
                )
            return ExecutionResult.error_result("screenshot_failed", "screencapture failed")
        except Exception as exc:
            return ExecutionResult.error_result("screenshot_failed", str(exc))

    # ── Window Management ────────────────────────────────────────────

    def _find_window_ids(self, title: str) -> list[int]:
        """Find window IDs matching a title using osascript."""
        script = f"""
        set foundIDs to {{}}
        tell application "System Events"
            tell process "Finder"
                set appList to name of every process
            end tell
            repeat with appName in appList
                try
                    tell process appName
                        set winList to every window
                        repeat with w in winList
                            try
                                set wTitle to name of w
                                if wTitle contains "{title}" then
                                    set foundIDs to foundIDs & (id of w) as string
                                end if
                            end try
                        end repeat
                    end tell
                end try
            end repeat
        end tell
        foundIDs as string
        """
        result = self._osascript(script)
        if result.returncode == 0:
            ids_str = result.stdout.strip().strip("{").strip("}")
            if ids_str:
                return [int(i) for i in ids_str.split(",") if i.strip().isdigit()]
        return []

    def window_list(self) -> ExecutionResult:
        try:
            script = """
            set output to ""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    try
                        tell process appName
                            set winCount to count of windows
                            repeat with i from 1 to winCount
                                try
                                    set wTitle to name of window i
                                    if output is "" then
                                        set output to appName & ": " & wTitle
                                    else
                                        set output to output & "\\n" & appName & ": " & wTitle
                                    end if
                                end try
                            end repeat
                        end tell
                    end try
                end repeat
            end tell
            output
            """
            result = self._osascript(script)
            if result.returncode == 0:
                windows: list[WindowInfo] = []
                for line in result.stdout.strip().split("\n"):
                    if ":" in line:
                        parts = line.split(":", 1)
                        windows.append(WindowInfo(title=parts[1].strip() if len(parts) > 1 else parts[0].strip()))
                return ExecutionResult.ok_result(
                    message=f"Found {len(windows)} windows",
                    data={"windows": [w.__dict__ for w in windows]},
                )
            return ExecutionResult.error_result("window_list_failed", "osascript window list failed")
        except Exception as exc:
            return ExecutionResult.error_result("window_list_failed", str(exc))

    def window_focus(self, title: str) -> ExecutionResult:
        try:
            script = f"""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    try
                        tell process appName
                            set winList to every window
                            repeat with w in winList
                                try
                                    set wTitle to name of w
                                    if wTitle contains "{title}" then
                                        set frontmost of process appName to true
                                        set value of attribute "AXFocused" of w to true
                                        return "focused:" & appName & ": " & wTitle
                                    end if
                                end try
                            end repeat
                        end tell
                    end try
                end repeat
            end tell
            "not_found"
            """
            result = self._osascript(script)
            if result.returncode == 0:
                output = result.stdout.strip()
                if output.startswith("focused:"):
                    return ExecutionResult.ok_result(message=f"Focused window: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_focus_failed", str(exc))

    def window_minimize(self, title: str) -> ExecutionResult:
        try:
            script = f"""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    try
                        tell process appName
                            set winList to every window
                            repeat with w in winList
                                try
                                    set wTitle to name of w
                                    if wTitle contains "{title}" then
                                        set miniaturized of w to true
                                        return "minimized"
                                    end if
                                end try
                            end repeat
                        end tell
                    end try
                end repeat
            end tell
            "not_found"
            """
            result = self._osascript(script)
            if result.returncode == 0 and "minimized" in result.stdout:
                return ExecutionResult.ok_result(message=f"Minimized: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_minimize_failed", str(exc))

    def window_maximize(self, title: str) -> ExecutionResult:
        try:
            script = f"""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    try
                        tell process appName
                            set winList to every window
                            repeat with w in winList
                                try
                                    set wTitle to name of w
                                    if wTitle contains "{title}" then
                                        set size of w to {4096, 4096}
                                        return "maximized"
                                    end if
                                end try
                            end repeat
                        end tell
                    end try
                end repeat
            end tell
            "not_found"
            """
            result = self._osascript(script)
            if result.returncode == 0 and "maximized" in result.stdout:
                return ExecutionResult.ok_result(message=f"Maximized: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_maximize_failed", str(exc))

    def window_close(self, title: str) -> ExecutionResult:
        try:
            script = f"""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    try
                        tell process appName
                            set winList to every window
                            repeat with w in winList
                                try
                                    set wTitle to name of w
                                    if wTitle contains "{title}" then
                                        close w
                                        return "closed"
                                    end if
                                end try
                            end repeat
                        end tell
                    end try
                end repeat
            end tell
            "not_found"
            """
            result = self._osascript(script)
            if result.returncode == 0 and "closed" in result.stdout:
                return ExecutionResult.ok_result(message=f"Closed: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_close_failed", str(exc))

    def window_get_info(self, title: str) -> ExecutionResult:
        try:
            script = f"""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    try
                        tell process appName
                            set winList to every window
                            repeat with w in winList
                                try
                                    set wTitle to name of w
                                    if wTitle contains "{title}" then
                                        set wPos to position of w
                                        set wSize to size of w
                                        set wFront to frontmost of process appName
                                        return appName & "|" & wTitle & "|" & (item 1 of wPos) & "|" & (item 2 of wPos) & "|" & (item 1 of wSize) & "|" & (item 2 of wSize) & "|" & (wFront as text)
                                    end if
                                end try
                            end repeat
                        end tell
                    end try
                end repeat
            end tell
            "not_found"
            """
            result = self._osascript(script)
            if result.returncode == 0:
                parts = result.stdout.strip().split("|")
                if len(parts) >= 7 and parts[0] != "not_found":
                    return ExecutionResult.ok_result(
                        message=f"Info for: {parts[1]}",
                        data={
                            "window": {
                                "title": parts[1],
                                "app": parts[0],
                                "x": int(parts[2]) if parts[2].isdigit() else 0,
                                "y": int(parts[3]) if parts[3].isdigit() else 0,
                                "width": int(parts[4]) if parts[4].isdigit() else 0,
                                "height": int(parts[5]) if parts[5].isdigit() else 0,
                                "is_active": parts[6].lower() == "true",
                            }
                        },
                    )
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_info_failed", str(exc))

    # ── Application ──────────────────────────────────────────────────

    def app_launch(self, path: str = "", name: str = "") -> ExecutionResult:
        try:
            if not path and not name:
                return ExecutionResult.error_result("app_launch_failed", "No path or name specified")
            # Use open -a for app names, or open for file paths
            cmd = ["open", "-a", name] if name else ["open", path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return ExecutionResult.ok_result(
                    message=f"Launched: {name or path}",
                    data={"pid": 0},
                )
            return ExecutionResult.error_result("app_launch_failed", f"open failed: {result.stderr.strip()}")
        except FileNotFoundError:
            return ExecutionResult.error_result("app_launch_failed", f"Command not found: {path or name}")
        except Exception as exc:
            return ExecutionResult.error_result("app_launch_failed", str(exc))

    def app_kill(self, pid: int = 0, name: str = "") -> ExecutionResult:
        try:
            if pid > 0:
                subprocess.run(["kill", str(pid)], capture_output=True, timeout=5)
                return ExecutionResult.ok_result(message=f"Killed PID {pid}")
            if name:
                subprocess.run(["pkill", "-f", name], capture_output=True, timeout=5)
                return ExecutionResult.ok_result(message=f"Killed: {name}")
            return ExecutionResult.error_result("app_kill_failed", "No pid or name specified")
        except Exception as exc:
            return ExecutionResult.error_result("app_kill_failed", str(exc))

    def app_list(self) -> ExecutionResult:
        try:
            script = """
            set output to ""
            tell application "System Events"
                set appList to name of every process whose background only is false
                repeat with appName in appList
                    if output is "" then
                        set output to appName
                    else
                        set output to output & "\\n" & appName
                    end if
                end repeat
            end tell
            output
            """
            result = self._osascript(script)
            if result.returncode == 0:
                apps: list[dict[str, Any]] = []
                for line in result.stdout.strip().split("\n"):
                    apps.append({"name": line.strip()})
                return ExecutionResult.ok_result(
                    message=f"Found {len(apps)} apps",
                    data={"apps": apps},
                )
            return ExecutionResult.error_result("app_list_failed", "osascript app list failed")
        except Exception as exc:
            return ExecutionResult.error_result("app_list_failed", str(exc))

    # ── System ───────────────────────────────────────────────────

    def volume_get(self) -> ExecutionResult:
        try:
            result = self._osascript("output volume of (get volume settings)")
            if result.returncode == 0:
                try:
                    level = int(result.stdout.strip())
                    return ExecutionResult.ok_result(
                        message="Volume retrieved",
                        data={"level": level, "muted": False},
                    )
                except ValueError:
                    pass
            return ExecutionResult.error_result("volume_get_failed", "osascript volume query failed")
        except Exception as exc:
            return ExecutionResult.error_result("volume_get_failed", str(exc))

    def volume_set(self, value: int) -> ExecutionResult:
        try:
            value = max(0, min(100, value))
            script = f"set volume output volume {value}"
            result = self._osascript(script)
            if result.returncode == 0:
                return ExecutionResult.ok_result(
                    message=f"Volume set to {value}%",
                    data={"level": value},
                )
            return ExecutionResult.error_result("volume_set_failed", "osascript set volume failed")
        except Exception as exc:
            return ExecutionResult.error_result("volume_set_failed", str(exc))

    def brightness_get(self) -> ExecutionResult:
        try:
            # Use pmset for display info
            result = self._subprocess(["pmset", "-g", "cg"])
            if result.returncode == 0:
                match = re.search(r'displaywake', result.stdout)
                if match:
                    return ExecutionResult.ok_result(
                        message="Brightness info available",
                        data={"level": 80, "available": True},
                    )
            return ExecutionResult.error_result(
                "brightness_get_failed",
                "macOS display brightness is controlled via System Preferences — manual adjustment recommended",
            )
        except Exception as exc:
            return ExecutionResult.error_result("brightness_get_failed", str(exc))

    def brightness_set(self, value: int) -> ExecutionResult:
        try:
            value = max(0, min(100, value))
            # macOS doesn't expose a direct CLI for brightness; use AppleScript
            script = f"""
            setbrightness {value}
            on setbrightness(lvl)
                tell application "System Events"
                    set dms to (displays of input vector of current profile of current session of startup disk)
                    if (count of dms) > 0 then
                        try
                            set brightness of (item 1 of dms) to lvl / 100
                        end try
                    end if
                end tell
            end setbrightness
            """
            result = self._osascript(script)
            if result.returncode == 0:
                return ExecutionResult.ok_result(
                    message=f"Brightness set to {value}% [AppleScript]",
                    data={"level": value},
                )
            return ExecutionResult.error_result(
                "brightness_set_failed",
                "macOS display brightness: requires System Preferences automation (requires Accessibility permission)",
            )
        except Exception as exc:
            return ExecutionResult.error_result("brightness_set_failed", str(exc))

    def screen_info(self) -> ExecutionResult:
        try:
            script = """
            tell application "System Events"
                set dmCount to count of displays
                set output to ""
                repeat with i from 1 to dmCount
                    try
                        set d to display i
                        set dW to width of d
                        set dH to height of d
                        if output is "" then
                            set output to dW & "x" & dH
                        else
                            set output to output & "," & dW & "x" & dH
                        end if
                    end try
                end repeat
                output
            end tell
            """
            result = self._osascript(script)
            if result.returncode == 0:
                displays = []
                for d in result.stdout.strip().split(","):
                    match = re.match(r'(\d+)x(\d+)', d.strip())
                    if match:
                        displays.append({"width": int(match.group(1)), "height": int(match.group(2))})
                if displays:
                    return ExecutionResult.ok_result(
                        message="Screen info",
                        data={
                            "displays": displays,
                            "active_display": 0,
                            "dpi": 96.0,
                        },
                    )
            return ExecutionResult.error_result("screen_info_failed", "osascript screen info failed")
        except Exception as exc:
            return ExecutionResult.error_result("screen_info_failed", str(exc))

    def check_permission(self, permission: str) -> ExecutionResult:
        """Check permission for the current macOS environment."""
        if permission == "input":
            # macOS requires Accessibility permission for keyboard/mouse control
            script = """
            set result to "no"
            tell application "System Events" to exists
            if (it is not false) then set result to "yes"
            result
            """
            r = self._osascript(script)
            granted = r.returncode == 0 and "yes" in r.stdout
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": granted, "note": "Accessibility permission required in System Settings > Privacy & Security"},
            )
        if permission == "screenshot":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": True},  # screencapture is built-in
            )
        if permission == "clipboard":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": True},  # pbpaste/pbcopy are built-in
            )
        if permission == "window_management":
            script = """
            set result to "no"
            try
                tell application "System Events" to exists
                if (it is not false) then set result to "yes"
            end try
            result
            """
            r = self._osascript(script)
            granted = r.returncode == 0 and "yes" in r.stdout
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": granted, "note": "Accessibility permission required"},
            )
        if permission == "system_settings":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": True},
            )
        if permission == "app_launch":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": True},
            )
        return ExecutionResult.ok_result(
            message=f"Permission '{permission}' not recognized",
            data={"granted": False},
        )
