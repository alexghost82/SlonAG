"""Computer control action for SlonAG.

This is the legacy entry point. It routes supported actions through the
new `computer_control.executor` pipeline for safety and E2E safety,
while preserving legacy helpers (random_data, user_data, screen_find)
for backward compatibility.
"""

from __future__ import annotations

import random
import string
import time
from pathlib import Path
from typing import Any

from computer_control.platform import build_platform_adapter
from computer_control.executor import validate_action, run_computer_control
from mark.tools.contracts import ToolResult

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False


def _safe_screenshot_path(requested: str | None) -> Path:
    """Resolve a screenshot save path under ~."""
    try:
        p = Path(requested).expanduser().resolve()
        if p.is_relative_to(Path.home()):
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    return Path.home() / "Desktop" / "slon_screenshot.png"


# ── Legacy helpers (keep for backward compatibility) ───────────────

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()
    if dt == "first_name":
        return random.choice(_FIRST_NAMES)
    if dt == "last_name":
        return random.choice(_LAST_NAMES)
    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last = random.choice(_LAST_NAMES).lower()
        num = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"
    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"
    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        return "".join(random.choices(chars, k=12))
    return ""


def _user_data(field: str, session_memory=None) -> str:
    """Pull real data from session memory."""
    if session_memory is None:
        return "session_memory not available"
    return str(session_memory.get(field, ""))


def _screenshot(save_path: str | None = None) -> str:
    """Capture screen (legacy)."""
    if not _PYAUTOGUI:
        return "pyautogui не установлен"
    try:
        path = str(_safe_screenshot_path(save_path))
        img = pyautogui.screenshot()
        img.save(path)
        return f"Скриншот сохранён: {path}"
    except Exception as exc:
        return f"Не удалось сделать скриншот: {exc}"


def _focus_window(title: str) -> str:
    """Bring window to foreground (legacy fallback)."""
    if not _PYAUTOGUI:
        return "pyautogui не установлен"
    try:
        # Try to find and click a window by title is hard with pyautogui alone
        return f"focus_window: '{title}' (legacy — check platform adapter)"
    except Exception as exc:
        return f"Не удалось активировать окно: {exc}"


# ── Main dispatch ──────────────────────────────────────────────────

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> ToolResult:
    """Dispatch table for all computer control actions.

    Routes through the new executor pipeline. Legacy features
    (random_data, user_data, screen_find, screen_click) remain here.
    """
    params = dict(parameters or {})
    action = params.get("action", "").lower().strip()

    if not action:
        return ToolResult(
            ok=False, code="no_action",
            message="Не указано действие (action).",
        )

    if player:
        try:
            player.write_log(f"[Computer] {action}")
        except Exception:
            pass

    # ── Legacy actions (not yet in new executor) ─────────────────

    if action == "random_data":
        data_type = params.get("type", "name")
        result = _random_data(data_type)
        return ToolResult(ok=True, code="ok", message=f"Сгенерировано: {result}", data={"data": result})

    if action == "user_data":
        field = params.get("field", "")
        result = _user_data(field, session_memory)
        return ToolResult(ok=True, code="ok", message=f"Данные: {result}", data={"data": result})

    if action == "screenshot":
        path = params.get("path")
        result = _screenshot(path)
        ok = not result.startswith("pyautogui") and not result.startswith("Не удалось")
        return ToolResult(ok=ok, code="ok" if ok else "screenshot_fail", message=result)

    if action == "focus_window":
        title = params.get("title", "")
        result = _focus_window(title)
        return ToolResult(ok=True, code="ok", message=result)

    if action == "screen_find":
        desc = params.get("description", "")
        return ToolResult(
            ok=False, code="screen_find_unsupported",
            message=f"screen_find не доступен без AI vision: {desc}",
        )

    if action == "screen_click":
        desc = params.get("description", "")
        return ToolResult(
            ok=False, code="screen_click_unsupported",
            message=f"screen_click не доступен без AI vision: {desc}",
        )

    if action == "clear_field":
        return ToolResult(ok=True, code="ok", message="clear_field (legacy — use keyboard.hotkey ctrl+a then delete)")

    # ── Route through new executor pipeline ─────────────────────

    # Validate
    validation = validate_action(action, params)
    if not validation.ok:
        return ToolResult(
            ok=False, code=validation.code,
            message=validation.message,
        )

    # Build parameters dict for the executor
    executor_params: dict[str, Any] = dict(params)

    # Execute
    result = run_computer_control(action=action, parameters=executor_params, adapter=build_platform_adapter("auto"))

    return result
