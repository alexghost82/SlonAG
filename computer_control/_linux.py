"""Linux (X11 / Wayland) platform adapter for computer control.

Uses: pyautogui (mouse/keyboard), XDoX / xdotool (window mgmt),
      xset/xbacklight (brightness), amixer/pactl (volume).
Falls back to subprocess calls when GUI libraries are unavailable.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
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


class LinuxPlatformAdapter:
    """Real desktop automation for Linux via XDoX, xdotool, and pyautogui."""

    def __init__(self) -> None:
        self._platform: OSPlatform = OSPlatform.LINUX
        self._xdotool_available: bool = self._check_tool("xdotool")
        self._xwininfo_available: bool = self._check_tool("xwininfo")
        self._xset_available: bool = self._check_tool("xset")
        self._has_wayland: bool = os.environ.get("XDG_SESSION_TYPE") == "wayland"
        self._pyautogui_available: bool = self._check_pyautogui()

    @property
    def platform(self) -> OSPlatform:
        return self._platform

    @staticmethod
    def _check_tool(name: str) -> bool:
        try:
            subprocess.run(["which", name], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

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

    def _subprocess(self, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

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
            pyautogui.hotkey(*keys)
            return ExecutionResult.ok_result(message=f"Hotkey: {'+'.join(keys)}")
        except Exception as exc:
            return ExecutionResult.error_result("keyboard_hotkey_failed", f"Hotkey failed: {exc}")

    def keyboard_press(self, key: str, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            self._require_pyautogui()
            import pyautogui
            pyautogui.press(key)
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
            # Try xclip first, then xsel
            for cmd in [["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
                try:
                    result = self._subprocess(cmd)
                    if result.returncode == 0 and result.stdout:
                        return ExecutionResult.ok_result(message="Clipboard read", data={"content": result.stdout})
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            return ExecutionResult.error_result("clipboard_read_failed", "xclip/xsel not available")
        except Exception as exc:
            return ExecutionResult.error_result("clipboard_read_failed", str(exc))

    def clipboard_write(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        try:
            if token is not None:
                token.check()
            import subprocess
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                capture_output=True,
                timeout=5,
            )
            if proc.returncode == 0:
                return ExecutionResult.ok_result(message=f"Clipboard written: {text[:60]}")
            return ExecutionResult.error_result("clipboard_write_failed", "xclip write failed")
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

            # Try import (ImageMagick) first, then scrot, then gnome-screenshot
            for cmd in [
                ["import", "-window", "root", dest],
                ["scrot", dest],
                ["gnome-screenshot", "-f", dest],
                ["grim", dest],  # Wayland
            ]:
                try:
                    result = self._subprocess(cmd)
                    if result.returncode == 0 and Path(dest).exists():
                        size = Path(dest).stat().st_size
                        return ExecutionResult.ok_result(
                            message=f"Screenshot saved: {dest}",
                            data={"path": dest, "size": size},
                        )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue

            return ExecutionResult.error_result("screenshot_failed", "No screenshot tool available (try install scrot or import)")
        except Exception as exc:
            return ExecutionResult.error_result("screenshot_failed", str(exc))

    # ── Window Management ────────────────────────────────────────────

    def window_list(self) -> ExecutionResult:
        try:
            if not self._xdotool_available:
                return ExecutionResult.error_result(
                    "window_list_failed", "xdotool not installed. Install: apt install xdotool"
                )
            result = self._subprocess(["xdotool", "search", "--name", "."])
            if result.returncode != 0:
                return ExecutionResult.error_result("window_list_failed", "xdotool search failed")

            window_ids = result.stdout.strip().split("\n")
            windows: list[WindowInfo] = []
            for wid in window_ids[:50]:  # Limit to 50 windows
                try:
                    info = self._get_window_info(wid)
                    if info:
                        windows.append(info)
                except Exception:
                    continue
            return ExecutionResult.ok_result(
                message=f"Found {len(windows)} windows",
                data={"windows": [w.__dict__ for w in windows]},
            )
        except Exception as exc:
            return ExecutionResult.error_result("window_list_failed", str(exc))

    def _get_window_info(self, win_id: str) -> WindowInfo | None:
        try:
            result = self._subprocess([
                "xdotool", "getwindowgeometry", "--shell", win_id
            ])
            if result.returncode != 0:
                return None
            # Parse xdotool output: WIDTH=800\nHEIGHT=600\nX=0\nY=0\nWINDOW=12345
            data = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()

            pid = 0
            try:
                pid_result = self._subprocess(["xdotool", "getwindowpid", win_id])
                if pid_result.returncode == 0:
                    pid = int(pid_result.stdout.strip())
            except Exception:
                pass

            title = ""
            try:
                title_result = self._subprocess(["xdotool", "getwindowname", win_id])
                if title_result.returncode == 0:
                    title = title_result.stdout.strip()
            except Exception:
                pass

            return WindowInfo(
                title=title or "Unknown",
                pid=pid,
                x=int(data.get("X", 0)),
                y=int(data.get("Y", 0)),
                width=int(data.get("WIDTH", 0)),
                height=int(data.get("HEIGHT", 0)),
            )
        except Exception:
            return None

    def window_focus(self, title: str) -> ExecutionResult:
        try:
            if not self._xdotool_available:
                return ExecutionResult.error_result("window_focus_failed", "xdotool not installed")
            result = self._subprocess(["xdotool", "search", "--name", title, "--onlyvisible", "windowactivate", "--sync"])
            if result.returncode == 0:
                return ExecutionResult.ok_result(message=f"Focused window: {title}")
            # Fallback: search without --onlyvisible
            result = self._subprocess(["xdotool", "search", "--name", title, "windowactivate", "--sync"])
            if result.returncode == 0:
                return ExecutionResult.ok_result(message=f"Focused window: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_focus_failed", str(exc))

    def window_minimize(self, title: str) -> ExecutionResult:
        try:
            if not self._xdotool_available:
                return ExecutionResult.error_result("window_minimize_failed", "xdotool not installed")
            result = self._subprocess(["xdotool", "search", "--name", title, "--onlyvisible", "windowminimize"])
            if result.returncode == 0:
                return ExecutionResult.ok_result(message=f"Minimized: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_minimize_failed", str(exc))

    def window_maximize(self, title: str) -> ExecutionResult:
        try:
            if not self._xdotool_available:
                return ExecutionResult.error_result("window_maximize_failed", "xdotool not installed")
            # xdotool maximize: windowmove + resize
            result = self._subprocess(["xdotool", "search", "--name", title, "--onlyvisible", "windowactivate"])
            if result.returncode == 0:
                # Get current screen size
                screen_result = self._subprocess(["xdpyinfo", "| grep 'dimensions:'"])
                if screen_result.returncode == 0:
                    match = re.search(r'(\d+)x(\d+)', screen_result.stdout)
                    if match:
                        w, h = int(match.group(1)), int(match.group(2))
                        self._subprocess(["xdotool", "search", "--name", title, "windowmove", "0", "0", "resize", str(w), str(h)])
                        return ExecutionResult.ok_result(message=f"Maximized: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_maximize_failed", str(exc))

    def window_close(self, title: str) -> ExecutionResult:
        try:
            if not self._xdotool_available:
                return ExecutionResult.error_result("window_close_failed", "xdotool not installed")
            result = self._subprocess(["xdotool", "search", "--name", title, "--onlyvisible", "windowclose"])
            if result.returncode == 0:
                return ExecutionResult.ok_result(message=f"Closed: {title}")
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_close_failed", str(exc))

    def window_get_info(self, title: str) -> ExecutionResult:
        try:
            if not self._xdotool_available:
                return ExecutionResult.error_result("window_info_failed", "xdotool not installed")
            result = self._subprocess(["xdotool", "search", "--name", title])
            if result.returncode == 0 and result.stdout.strip():
                win_id = result.stdout.strip().split("\n")[0]
                info = self._get_window_info(win_id)
                if info:
                    return ExecutionResult.ok_result(message=f"Info for: {info.title}", data={"window": info.__dict__})
            return ExecutionResult.error_result("window_not_found", f"Window not found: {title}")
        except Exception as exc:
            return ExecutionResult.error_result("window_info_failed", str(exc))

    # ── Application ──────────────────────────────────────────────────

    def app_launch(self, path: str = "", name: str = "") -> ExecutionResult:
        try:
            cmd = path if path else name
            if not cmd:
                return ExecutionResult.error_result("app_launch_failed", "No path or name specified")
            result = subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ExecutionResult.ok_result(
                message=f"Launched: {cmd}",
                data={"pid": result.pid},
            )
        except FileNotFoundError:
            return ExecutionResult.error_result("app_launch_failed", f"Command not found: {cmd}")
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
            result = self._subprocess(["ps", "-eo", "pid,comm,args", "--no-headers"])
            if result.returncode == 0:
                apps: list[dict[str, Any]] = []
                for line in result.stdout.strip().split("\n")[:50]:
                    parts = line.split(None, 2)
                    if len(parts) >= 2:
                        apps.append({"pid": int(parts[0]), "name": parts[1], "cmd": parts[2] if len(parts) > 2 else ""})
                return ExecutionResult.ok_result(
                    message=f"Found {len(apps)} processes",
                    data={"apps": apps},
                )
            return ExecutionResult.error_result("app_list_failed", "ps command failed")
        except Exception as exc:
            return ExecutionResult.error_result("app_list_failed", str(exc))

    # ── System ───────────────────────────────────────────────────────

    def volume_get(self) -> ExecutionResult:
        try:
            # Try pactl first (PipeWire), then amixer (ALSA)
            for cmd in [
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                ["amixer", "get", "Master"],
            ]:
                try:
                    result = self._subprocess(cmd)
                    if result.returncode == 0:
                        match = re.search(r'(\d+)%', result.stdout)
                        if match:
                            level = int(match.group(1))
                            return ExecutionResult.ok_result(
                                message="Volume retrieved",
                                data={"level": level, "muted": "Muted" in result.stdout},
                            )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            return ExecutionResult.error_result("volume_get_failed", "No volume control available")
        except Exception as exc:
            return ExecutionResult.error_result("volume_get_failed", str(exc))

    def volume_set(self, value: int) -> ExecutionResult:
        try:
            value = max(0, min(100, value))
            # Try pactl first
            for cmd in [
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
                ["amixer", "sset", "Master", f"{value}%"],
            ]:
                try:
                    result = self._subprocess(cmd)
                    if result.returncode == 0:
                        return ExecutionResult.ok_result(
                            message=f"Volume set to {value}%",
                            data={"level": value},
                        )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            return ExecutionResult.error_result("volume_set_failed", "No volume control available")
        except Exception as exc:
            return ExecutionResult.error_result("volume_set_failed", str(exc))

    def brightness_get(self) -> ExecutionResult:
        try:
            # Try backlight interface first
            backlight_path = Path("/sys/class/backlight")
            if backlight_path.exists():
                for dev in backlight_path.iterdir():
                    brightness_file = dev / "brightness"
                    max_file = dev / "max_brightness"
                    if brightness_file.exists() and max_file.exists():
                        current = int(brightness_file.read_text())
                        maximum = int(max_file.read_text())
                        level = int(current / maximum * 100) if maximum > 0 else 0
                        return ExecutionResult.ok_result(
                            message="Brightness retrieved",
                            data={"level": level},
                        )
            # Fallback: xbacklight
            result = self._subprocess(["xbacklight", "-get"])
            if result.returncode == 0:
                level = int(float(result.stdout.strip()))
                return ExecutionResult.ok_result(
                    message="Brightness retrieved",
                    data={"level": level},
                )
            return ExecutionResult.error_result("brightness_get_failed", "No brightness control available")
        except Exception as exc:
            return ExecutionResult.error_result("brightness_get_failed", str(exc))

    def brightness_set(self, value: int) -> ExecutionResult:
        try:
            value = max(0, min(100, value))
            result = self._subprocess(["xbacklight", "-set", str(value)])
            if result.returncode == 0:
                return ExecutionResult.ok_result(
                    message=f"Brightness set to {value}%",
                    data={"level": value},
                )
            return ExecutionResult.error_result("brightness_set_failed", "xbacklight failed")
        except Exception as exc:
            return ExecutionResult.error_result("brightness_set_failed", str(exc))

    def screen_info(self) -> ExecutionResult:
        try:
            result = self._subprocess(["xdpyinfo"])
            if result.returncode == 0:
                match = re.search(r'dimensions:\s+(\d+)x(\d+)', result.stdout)
                if match:
                    w, h = int(match.group(1)), int(match.group(2))
                    return ExecutionResult.ok_result(
                        message="Screen info",
                        data={"width": w, "height": h, "dpi": 96.0},
                    )
            return ExecutionResult.error_result("screen_info_failed", "xdpyinfo unavailable")
        except Exception as exc:
            return ExecutionResult.error_result("screen_info_failed", str(exc))

    def check_permission(self, permission: str) -> ExecutionResult:
        """Check permission for the current user/environment."""
        if permission == "input":
            # On X11/Wayland, input is generally available in a desktop session
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ},
            )
        if permission == "screenshot":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": self._check_tool("scrot") or self._check_tool("import") or self._check_tool("gnome-screenshot")},
            )
        if permission == "clipboard":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": self._check_tool("xclip") or self._check_tool("xsel")},
            )
        if permission == "window_management":
            return ExecutionResult.ok_result(
                message=f"Permission '{permission}' checked",
                data={"granted": self._xdotool_available},
            )
        if permission == "system_settings":
            # Volume/brightness require root/sudo in many cases
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
