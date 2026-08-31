"""Windows platform adapter for computer control.

Uses: pyautogui (mouse/keyboard), win32gui/win32con/win32process
      (window management), subprocess (app launch, window info),
      ctypes/psutil (clipboard, screen info).
Falls back gracefully when GUI libraries are unavailable.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from computer_control.platform import PlatformAdapter
from computer_control.types import (
    CancellationToken,
    ExecutionResult,
    MouseClickButton,
    OSPlatform,
    ScrollDirection,
    ScreenPosition,
    WindowInfo,
)


# -- Windows command security --

_WINDOWS_INJECTION_RE = re.compile(
    r'[;|&<>`]'               # shell metacharacters
    r'|\$\('                 # $(… substitution
    r'|%[A-Za-z_][A-Za-z0-9_]*%'  # env-var expansion like %COMSPEC%
)

_WINDOWS_CMD_INVOCATION_RE = re.compile(
    r'cmd\s*/[cCpP]\s'
    r'|powershell(?:\.exe)?\s'
    r'|cmd\.exe\b'
    r'|pwsh(?:\.exe)?\b',
    re.IGNORECASE,
)

_BLOCKED_BASENAMES = frozenset((
    'cmd', 'cmd.exe', 'powershell', 'powershell.exe',
    'pwsh', 'pwsh.exe', 'pwsh.dll',
    'cmdkey', 'cmdkey.exe',
    'cscript', 'cscript.exe',
    'wscript', 'wscript.exe',
    'runas', 'runas.exe',
    'schtasks', 'schtasks.exe',
    'reg', 'reg.exe',
))


def _validate_windows_launch_input(value: str) -> str | None:
    """Validate an app_launch argument.

    Returns *value* if safe, or *None* to reject it.
    """
    if not value:
        return None
    if _WINDOWS_INJECTION_RE.search(value):
        return None
    if _WINDOWS_CMD_INVOCATION_RE.search(value):
        return None
    base = Path(value).name.lower()
    if base in _BLOCKED_BASENAMES:
        return None
    return value


class WindowsPlatformAdapter(PlatformAdapter):
    """Real desktop automation for Windows via pyautogui, win32gui, ctypes."""

    def __init__(self) -> None:
        self._platform: OSPlatform = OSPlatform.WINDOWS
        self._pyautogui_available: bool = self._check_pyautogui()
        self._win32_available: bool = self._check_win32()
        self._pyperclip_available: bool = self._check_pyperclip()
        self._pycaw_available: bool = self._check_pycaw()

    @property
    def platform(self) -> OSPlatform:
        return self._platform

    # ── Dependency checks ──────────────────────────────────────────

    @staticmethod
    def _check_pyautogui() -> bool:
        try:
            import pyautogui  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_win32() -> bool:
        try:
            import win32gui  # noqa: F401
            import win32con  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_pyperclip() -> bool:
        try:
            import pyperclip  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_pycaw() -> bool:
        try:
            from pycaw.pycaw import AudioEndpointVolume  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Helper: PowerShell ─────────────────────────────────────────

    @staticmethod
    def _run_ps(script: str, capture: bool = True) -> ExecutionResult:
        """Run PowerShell script with error handling."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return ExecutionResult.error_result(
                    "ps_error", f"PowerShell error: {result.stderr.strip()}",
                )
            return ExecutionResult.ok_result(data={"output": result.stdout.strip()})
        except subprocess.TimeoutExpired:
            return ExecutionResult.error_result("ps_timeout", "PowerShell timed out (15s)")
        except FileNotFoundError:
            return ExecutionResult.error_result("no_powershell", "PowerShell not found")

    # ── Mouse ────────────────────────────────────────────────────────────────

    def mouse_move(
        self, x: int, y: int, token: CancellationToken | None = None
    ) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            pyautogui.moveTo(x, y, duration=0.2)
            return ExecutionResult.ok_result(
                message=f"Мышь перемещена в ({x}, {y})",
                data={"x": x, "y": y},
            )
        except Exception as exc:
            return ExecutionResult.error_result("mouse_move_fail", f"Не удалось переместить мышь: {exc}")

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
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            if x is not None and y is not None:
                pyautogui.moveTo(x, y, duration=0.1)
            pyautogui.click(clicks=clicks, button=button.value)
            return ExecutionResult.ok_result(
                message=f"Клик {clicks}x {button.value}",
                data={"button": button.value, "clicks": clicks, "x": x, "y": y},
            )
        except Exception as exc:
            return ExecutionResult.error_result("mouse_click_fail", f"Не удалось выполнить клик: {exc}")

    def mouse_drag(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: float = 0.5,
        token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            pyautogui.moveTo(x1, y1, duration=0.1)
            pyautogui.dragTo(x2, y2, duration=duration, button="left")
            return ExecutionResult.ok_result(
                message=f"Перетаскивание ({x1},{y1})→({x2},{y2})",
                data={"start": (x1, y1), "end": (x2, y2)},
            )
        except Exception as exc:
            return ExecutionResult.error_result("mouse_drag_fail", f"Не удалось перетащить: {exc}")

    # ── Keyboard ───────────────────────────────────────────────────

    def keyboard_type(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            pyautogui.write(text, interval=0.01)
            return ExecutionResult.ok_result(
                message=f"Напечатано {len(text)} символов",
                data={"text": text, "length": len(text)},
            )
        except Exception as exc:
            return ExecutionResult.error_result("keyboard_type_fail", f"Не удалось напечатать текст: {exc}")

    def keyboard_hotkey(self, keys: list[str], token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            pyautogui.hotkey(*keys)
            return ExecutionResult.ok_result(
                message=f"Горячая клавиша: {'+'.join(keys)}",
                data={"keys": keys},
            )
        except Exception as exc:
            return ExecutionResult.error_result("hotkey_fail", f"Не удалось нажать горячую клавишу: {exc}")

    def keyboard_press(self, key: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            pyautogui.press(key)
            return ExecutionResult.ok_result(
                message=f"Клавиша нажата: {key}",
                data={"key": key},
            )
        except Exception as exc:
            return ExecutionResult.error_result("key_press_fail", f"Не удалось нажать клавишу: {exc}")

    # ── Scroll ─────────────────────────────────────────────────────

    def scroll(
        self, direction: ScrollDirection, amount: int, token: CancellationToken | None = None
    ) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            delta = amount if direction == ScrollDirection.UP else -amount
            pyautogui.scroll(delta)
            return ExecutionResult.ok_result(
                message=f"Прокрутка {amount}x {direction.value}",
                data={"direction": direction.value, "amount": amount},
            )
        except Exception as exc:
            return ExecutionResult.error_result("scroll_fail", f"Не удалось прокрутить: {exc}")

    # ── Clipboard ──────────────────────────────────────────────────

    def clipboard_read(self, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyperclip_available:
            return ExecutionResult.error_result(
                "pyperclip_missing", "pyperclip не установлен. Установите: pip install pyperclip",
            )
        import pyperclip
        try:
            text = pyperclip.paste()
            return ExecutionResult.ok_result(
                message="Буфер обмена прочитан",
                data={"text": text},
            )
        except Exception as exc:
            return ExecutionResult.error_result("clipboard_read_fail", f"Не удалось прочитать буфер: {exc}")

    def clipboard_write(self, text: str, token: CancellationToken | None = None) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyperclip_available:
            return ExecutionResult.error_result(
                "pyperclip_missing", "pyperclip не установлен. Установите: pip install pyperclip",
            )
        import pyperclip
        try:
            pyperclip.copy(text)
            return ExecutionResult.ok_result(
                message=f"Буфер обмена записан ({len(text)} символов)",
                data={"text": text},
            )
        except Exception as exc:
            return ExecutionResult.error_result("clipboard_write_fail", f"Не удалось записать буфер: {exc}")

    # ── Screenshot ─────────────────────────────────────────────────

    def screenshot(
        self, save_path: str | None = None, token: CancellationToken | None = None
    ) -> ExecutionResult:
        if token:
            token.check()
        if not self._pyautogui_available:
            return ExecutionResult.error_result(
                "pyautogui_missing", "pyautogui не установлен. Установите: pip install pyautogui",
            )
        import pyautogui
        try:
            path = save_path or str(Path.home() / "Desktop" / "slon_screenshot.png")
            img = pyautogui.screenshot()
            img.save(path)
            return ExecutionResult.ok_result(
                message="Скриншот сохранён",
                data={"path": path, "width": img.width, "height": img.height},
            )
        except Exception as exc:
            return ExecutionResult.error_result("screenshot_fail", f"Не удалось сделать скриншот: {exc}")

    # ── Window management ─────────────────────────────────────────

    def window_list(self) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result(
                "win32_missing", "pywin32 не установлен. Установите: pip install pywin32",
            )
        import win32gui

        windows: list[WindowInfo] = []

        def enum_cb(hwnd: int, _windows: list[WindowInfo]) -> None:
            try:
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return
                pid = 0
                try:
                    import win32process
                    pid, _ = win32process.GetWindowThreadProcessId(hwnd)
                except Exception:
                    pass
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                    is_minimized = bool(style & win32con.WS_MINIMIZE)
                    is_maximized = bool(style & win32con.WS_MAXIMIZE)
                except Exception:
                    rect = (0, 0, 0, 0)
                    is_minimized = False
                    is_maximized = False
                _windows.append(
                    WindowInfo(
                        title=title, pid=pid,
                        x=rect[0], y=rect[1],
                        width=rect[2] - rect[0],
                        height=rect[3] - rect[1],
                        is_minimized=is_minimized,
                        is_maximized=is_maximized,
                    )
                )
            except Exception:
                pass

        try:
            win32gui.EnumWindows(enum_cb, windows)
        except Exception:
            pass

        return ExecutionResult.ok_result(
            message=f"Найдено {len(windows)} окон",
            data={"windows": [w.__dict__ for w in windows]},
        )

    def _find_window(self, title: str) -> list[int]:
        """Find window HWNDs by title substring."""
        import win32gui

        handles: list[int] = []

        def enum_cb(hwnd: int, _handles: list[int]) -> None:
            try:
                win_title = win32gui.GetWindowText(hwnd)
                if title.lower() in win_title.lower():
                    _handles.append(hwnd)
            except Exception:
                pass

        try:
            win32gui.EnumWindows(enum_cb, handles)
        except Exception:
            pass
        return handles

    def window_focus(self, title: str) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result("win32_missing", "pywin32 не установлен")
        handles = self._find_window(title)
        if not handles:
            return ExecutionResult.error_result("window_not_found", f"Окно не найдено: '{title}'")
        import win32gui
        import win32con
        try:
            hwnd = handles[0]
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return ExecutionResult.ok_result(message=f"Окно активно: '{title}'")
        except Exception as exc:
            return ExecutionResult.error_result("window_focus_fail", f"Не удалось активировать окно: {exc}")

    def window_minimize(self, title: str) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result("win32_missing", "pywin32 не установлен")
        handles = self._find_window(title)
        if not handles:
            return ExecutionResult.error_result("window_not_found", f"Окно не найдено: '{title}'")
        import win32gui
        import win32con
        try:
            win32gui.ShowWindow(handles[0], win32con.SW_MINIMIZE)
            return ExecutionResult.ok_result(message=f"Окно минимизировано: '{title}'")
        except Exception as exc:
            return ExecutionResult.error_result("window_minimize_fail", f"Не удалось минимизировать: {exc}")

    def window_maximize(self, title: str) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result("win32_missing", "pywin32 не установлен")
        handles = self._find_window(title)
        if not handles:
            return ExecutionResult.error_result("window_not_found", f"Окно не найдено: '{title}'")
        import win32gui
        import win32con
        try:
            win32gui.ShowWindow(handles[0], win32con.SW_MAXIMIZE)
            return ExecutionResult.ok_result(message=f"Окно развернуто: '{title}'")
        except Exception as exc:
            return ExecutionResult.error_result("window_maximize_fail", f"Не удалось развернуть: {exc}")

    def window_close(self, title: str) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result("win32_missing", "pywin32 не установлен")
        handles = self._find_window(title)
        if not handles:
            return ExecutionResult.error_result("window_not_found", f"Окно не найдено: '{title}'")
        import win32gui
        import win32con
        try:
            win32gui.PostMessage(handles[0], win32con.WM_CLOSE, 0, 0)
            return ExecutionResult.ok_result(message=f"Окно закрыто: '{title}'")
        except Exception as exc:
            return ExecutionResult.error_result("window_close_fail", f"Не удалось закрыть окно: {exc}")

    def window_get_info(self, title: str) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result("win32_missing", "pywin32 не установлен")
        handles = self._find_window(title)
        if not handles:
            return ExecutionResult.error_result("window_not_found", f"Окно не найдено: '{title}'")
        try:
            import win32gui
            import win32con
            import win32process
            hwnd = handles[0]
            rect = win32gui.GetWindowRect(hwnd)
            pid, _ = win32process.GetWindowThreadProcessId(hwnd)
            info = WindowInfo(
                title=win32gui.GetWindowText(hwnd),
                pid=pid,
                x=rect[0], y=rect[1],
                width=rect[2] - rect[0], height=rect[3] - rect[1],
            )
            return ExecutionResult.ok_result(
                message=f"Информация об окне: '{title}'",
                data=info.__dict__,
            )
        except Exception as exc:
            return ExecutionResult.error_result("window_info_fail", f"Не удалось получить информацию: {exc}")

    # ── App management ─────────────────────────────────────────────

    def app_launch(self, path: str = "", name: str = "") -> ExecutionResult:
        cmd = path or name
        if not cmd:
            return ExecutionResult.error_result("missing_args", "Не указаны путь или имя приложения")
        # Security: validate input to prevent command injection.
        validated = _validate_windows_launch_input(cmd)
        if validated is None:
            return ExecutionResult.error_result(
                "app_launch_injection",
                "Отказано: подозрительный символ в пути или имени",
            )
        try:
            # Safe: argv list, no shell=True.
            proc = subprocess.Popen(
                [validated],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ExecutionResult.ok_result(
                message=f"Приложение запущено: {cmd}",
                data={"pid": proc.pid},
            )
        except Exception as exc:
            return ExecutionResult.error_result("app_launch_fail", f"Не удалось запустить: {exc}")

    def app_kill(self, pid: int = 0, name: str = "") -> ExecutionResult:
        try:
            if pid > 0:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True, timeout=5,
                )
            elif name:
                subprocess.run(
                    ["taskkill", "/IM", name, "/F"],
                    capture_output=True, timeout=5,
                )
            else:
                return ExecutionResult.error_result("missing_args", "Укажите PID или имя процесса")
            return ExecutionResult.ok_result(
                message=f"Процесс завершён: pid={pid} name={name}",
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult.error_result("process_timeout", f"Не удалось завершить процесс: таймаут 5s")
        except Exception as exc:
            return ExecutionResult.error_result("app_kill_fail", f"Не удалось завершить процесс: {exc}")

    def app_list(self) -> ExecutionResult:
        result = self._run_ps(
            "$procs = Get-Process | Select-Object Name, Id | ConvertTo-Json -Compress; "
            "Write-Output $procs",
        )
        if not result.ok:
            return result
        try:
            output = result.data.get("output", "[]")
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("["):
                    output = line
                    break
            apps_data = json.loads(output)
            apps = [
                AppInfo(name=a["Name"], pid=int(a["Id"]))
                for a in apps_data if isinstance(a, dict) and "Name" in a
            ]
            return ExecutionResult.ok_result(
                message=f"Найдено {len(apps)} процессов",
                data={"apps": [a.__dict__ for a in apps]},
            )
        except Exception:
            return ExecutionResult.ok_result(
                message="Список приложений пуст (JSON parse error)",
                data={"apps": []},
            )

    # ── System settings ────────────────────────────────────────────

    def volume_get(self) -> ExecutionResult:
        if self._pycaw_available:
            try:
                from pycaw.pycaw import AudioEndpointVolume, ua_func  # noqa: F401
                from comtypes.gen import DeviceTopology  # noqa: F401
                u = ua_func().GetEndpointVolume()
                vol = u.MasterVolumeLevelScalar
                u.ReleaseCOMObject()
                return ExecutionResult.ok_result(
                    message="Громкость получена",
                    data={"level": int(vol * 100), "muted": False},
                )
            except Exception:
                pass
        return ExecutionResult.error_result(
            "volume_unsupported",
            "Управление громкостью на Windows требует pycaw (pip install pycaw)",
        )

    def volume_set(self, value: int) -> ExecutionResult:
        if self._pycaw_available:
            try:
                from pycaw.pycaw import ua_func  # noqa: F401
                u = ua_func().GetEndpointVolume()
                u.MasterVolumeLevelScalar = value / 100.0
                u.ReleaseCOMObject()
                return ExecutionResult.ok_result(
                    message=f"Громкость установлена на {value}%",
                    data={"level": value},
                )
            except Exception as exc:
                return ExecutionResult.error_result("volume_set_fail", f"Не удалось установить громкость: {exc}")
        return ExecutionResult.error_result(
            "volume_unsupported",
            "Управление громкостью на Windows требует pycaw (pip install pycaw)",
        )

    def brightness_get(self) -> ExecutionResult:
        return ExecutionResult.error_result(
            "brightness_unsupported",
            "Управление яркостью на Windows не поддерживается через стандартные API. "
            "Используйте vendor-утилиты (NVidia, Intel, AMD).",
        )

    def brightness_set(self, value: int) -> ExecutionResult:
        return ExecutionResult.error_result(
            "brightness_unsupported",
            "Управление яркостью на Windows не поддерживается через стандартные API. "
            "Используйте vendor-утилиты (NVidia, Intel, AMD).",
        )

    # ── Screen info ────────────────────────────────────────────────

    def screen_info(self) -> ExecutionResult:
        if not self._win32_available:
            return ExecutionResult.error_result("win32_missing", "pywin32 не установлен")
        import win32api
        import win32con
        try:
            width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
            return ExecutionResult.ok_result(
                message="Информация о экране",
                data={"width": width, "height": height, "dpi": 96.0, "active_display": 0},
            )
        except Exception as exc:
            return ExecutionResult.error_result("screen_info_fail", f"Не удалось получить информацию о экране: {exc}")

    def check_permission(self, permission: str) -> ExecutionResult:
        available_tools: dict[str, bool] = {
            "mouse_keyboard": self._pyautogui_available,
            "window_management": self._win32_available,
            "clipboard": self._pyperclip_available,
            "volume": self._pycaw_available,
        }
        permission_map: dict[str, bool] = {
            "input": self._pyautogui_available,
            "window_management": self._win32_available,
            "clipboard": self._pyperclip_available,
            "screenshot": self._pyautogui_available,
            "system_settings": self._pycaw_available,
            "app_launch": True,
        }
        granted = permission_map.get(permission, False)
        return ExecutionResult.ok_result(
            message=f"Проверка разрешения: {permission}",
            data={"granted": granted, "tools": available_tools},
        )


# ── Builder ─────────────────────────────────────────────────────────


def build_windows_adapter() -> PlatformAdapter:
    """Build a Windows adapter using win32gui, pyautogui, and ctypes."""
    try:
        return WindowsPlatformAdapter()
    except Exception as exc:
        raise RuntimeError(f"Windows desktop automation unavailable: {exc}") from exc
