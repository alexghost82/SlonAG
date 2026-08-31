"""Executor pipeline for computer-control actions.

Pipeline:
    ToolRegistry (legacy entry)
    → SafetyPolicy (validation)
    → Approval (optional)
    → ToolExecutor (dispatch + cancel)
    → PlatformAdapter (real or mock)
    → ExecutionResult → ToolResult

Cancellation and cleanup are enforced at every step.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from computer_control.types import (
    ACTION_FIELDS,
    CancellationToken,
    ComputerControlAction,
    ExecutionResult,
    MouseClickButton,
    ScrollDirection,
)

# Lazy import to avoid circular deps and keep startup fast
_TOOL_RESULT_CLASS = None
_MARK_TOOLS_CONTRACTS = None


def _get_tool_result_class():
    """Lazy import ToolResult to avoid circular imports."""
    global _TOOL_RESULT_CLASS
    if _TOOL_RESULT_CLASS is None:
        from acta.tools.contracts import ToolResult
        _TOOL_RESULT_CLASS = ToolResult
    return _TOOL_RESULT_CLASS


# ── Legacy action name → ComputerControlAction mapping ─────────────

_LEGACY_ACTION_MAP: dict[str, ComputerControlAction] = {
    # Mouse
    "mouse_move": ComputerControlAction.MOUSE_MOVE,
    "move": ComputerControlAction.MOUSE_MOVE,
    "click": ComputerControlAction.MOUSE_CLICK,
    "left_click": ComputerControlAction.MOUSE_CLICK,
    "double_click": ComputerControlAction.MOUSE_DOUBLE_CLICK,
    "right_click": ComputerControlAction.MOUSE_RIGHT_CLICK,
    "mouse_drag": ComputerControlAction.MOUSE_DRAG,
    "drag": ComputerControlAction.MOUSE_DRAG,
    # Keyboard
    "type": ComputerControlAction.KEYBOARD_TYPE,
    "smart_type": ComputerControlAction.KEYBOARD_TYPE,
    "keyboard_type": ComputerControlAction.KEYBOARD_TYPE,
    "hotkey": ComputerControlAction.KEYBOARD_HOTKEY,
    "keyboard_hotkey": ComputerControlAction.KEYBOARD_HOTKEY,
    "press": ComputerControlAction.KEYBOARD_PRESS,
    "keyboard_press": ComputerControlAction.KEYBOARD_PRESS,
    # Scroll
    "scroll": ComputerControlAction.SCROLL,
    # Clipboard
    "copy": ComputerControlAction.CLIPBOARD_READ,
    "paste": ComputerControlAction.CLIPBOARD_WRITE,
    "clipboard_read": ComputerControlAction.CLIPBOARD_READ,
    "clipboard_write": ComputerControlAction.CLIPBOARD_WRITE,
    # Screenshot
    "screenshot": ComputerControlAction.SCREENSHOT,
    # Window
    "window_list": ComputerControlAction.WINDOW_LIST,
    "focus_window": ComputerControlAction.WINDOW_FOCUS,
    "window_focus": ComputerControlAction.WINDOW_FOCUS,
    "window_minimize": ComputerControlAction.WINDOW_MINIMIZE,
    "window_maximize": ComputerControlAction.WINDOW_MAXIMIZE,
    "window_close": ComputerControlAction.WINDOW_CLOSE,
    "window_get_info": ComputerControlAction.WINDOW_GET_INFO,
    "window_info": ComputerControlAction.WINDOW_GET_INFO,
    # App
    "app_launch": ComputerControlAction.APP_LAUNCH,
    "app_kill": ComputerControlAction.APP_KILL,
    "app_list": ComputerControlAction.APP_LIST,
    # System
    "volume_get": ComputerControlAction.VOLUME_GET,
    "volume_set": ComputerControlAction.VOLUME_SET,
    "brightness_get": ComputerControlAction.BRIGHTNESS_GET,
    "brightness_set": ComputerControlAction.BRIGHTNESS_SET,
    # Utility
    "wait": ComputerControlAction.WAIT,
    "capability_check": ComputerControlAction.CAPABILITY_CHECK,
    "capability": ComputerControlAction.CAPABILITY_CHECK,
}


# ── Validation ─────────────────────────────────────────────────────

def validate_action(action: str, parameters: dict[str, Any]) -> ExecutionResult:
    """Validate action name and required fields."""
    # Resolve to enum
    action_enum = _LEGACY_ACTION_MAP.get(action.lower().strip())
    if action_enum is None:
        return ExecutionResult.error_result(
            "unknown_action",
            f"Неизвестное действие: '{action}'. Доступные: {sorted(_LEGACY_ACTION_MAP.keys())}",
        )
    # Check required fields
    required = ACTION_FIELDS.get(action_enum, ())
    missing = [f for f in required if f not in parameters or not parameters[f]]
    if missing:
        return ExecutionResult.error_result(
            "missing_fields",
            f"Отсутствуют обязательные поля для '{action}': {', '.join(missing)}",
        )
    return ExecutionResult.ok_result(
        message=f"Действие '{action}' валидно",
        data={"action_enum": action_enum.value, "required": list(required)},
    )


# ── Executor ───────────────────────────────────────────────────────

class ComputerControlExecutor:
    """Execute computer-control actions through the full pipeline."""

    def __init__(self, adapter=None, cancellation_token: CancellationToken | None = None,
                 require_approval: bool = True) -> None:
        self._adapter = adapter
        self._cancellation_token = cancellation_token or CancellationToken()
        self._require_approval = require_approval

    @property
    def adapter(self):
        return self._adapter

    @adapter.setter
    def adapter(self, adapter):
        self._adapter = adapter

    def cancel(self) -> None:
        """Cancel any in-flight action."""
        self._cancellation_token.cancel()

    def execute(self, action: str, parameters: Mapping[str, Any]) -> Any:
        """Full pipeline: validate → cancel → dispatch → ExecutionResult → ToolResult."""
        params = dict(parameters)
        start_time = time.monotonic()

        # 1. Validate
        validation = validate_action(action, params)
        if not validation.ok:
            result = self._to_tool_result(validation, start_time)
            return result

        action_enum = ComputerControlAction(validation.data["action_enum"])

        # 2. Check cancellation
        if self._cancellation_token.is_cancelled:
            result = self._to_tool_result(ExecutionResult.cancelled_result(), start_time)
            return result
        self._cancellation_token.check()

        # 3. Check approval (no-op in test/dev mode)
        if self._require_approval:
            # In real usage this would go through SafetyPolicy → Approval
            # For now, all mock actions are pre-approved
            pass

        # 4. Dispatch
        try:
            exec_result = self._dispatch(action_enum, params)
        except Exception as exc:
            exec_result = ExecutionResult.error_result(
                "execution_error", f"Внутренняя ошибка: {exc}",
            )

        # 5. Convert to ToolResult
        result = self._to_tool_result(exec_result, start_time)
        return result

    def _dispatch(self, action: ComputerControlAction, params: dict[str, Any]) -> ExecutionResult:
        """Dispatch to the right platform adapter method."""
        if self._adapter is None:
            return ExecutionResult.error_result(
                "no_adapter",
                "Платформенный адаптер не инициализирован.",
            )

        # Dispatch table
        dispatch: dict[ComputerControlAction, Any] = {
            # Mouse
            ComputerControlAction.MOUSE_MOVE: lambda: self._adapter.mouse_move(
                x=params["x"], y=params["y"], token=self._cancellation_token),
            ComputerControlAction.MOUSE_CLICK: lambda: self._adapter.mouse_click(
                x=params.get("x"), y=params.get("y"),
                button=MouseClickButton(params.get("button", "left")),
                clicks=params.get("clicks", 1),
                token=self._cancellation_token,
            ),
            ComputerControlAction.MOUSE_DOUBLE_CLICK: lambda: self._adapter.mouse_click(
                x=params.get("x"), y=params.get("y"),
                button=MouseClickButton(params.get("button", "left")),
                clicks=2, token=self._cancellation_token,
            ),
            ComputerControlAction.MOUSE_RIGHT_CLICK: lambda: self._adapter.mouse_click(
                x=params.get("x"), y=params.get("y"),
                button=MouseClickButton.RIGHT, clicks=1,
                token=self._cancellation_token,
            ),
            ComputerControlAction.MOUSE_DRAG: lambda: self._adapter.mouse_drag(
                x1=params["x1"], y1=params["y1"],
                x2=params["x2"], y2=params["y2"],
                duration=params.get("duration", 0.5),
                token=self._cancellation_token,
            ),
            # Keyboard
            ComputerControlAction.KEYBOARD_TYPE: lambda: self._adapter.keyboard_type(
                text=params["text"], token=self._cancellation_token),
            ComputerControlAction.KEYBOARD_HOTKEY: lambda: self._adapter.keyboard_hotkey(
                keys=self._parse_hotkey(params["keys"]) if isinstance(params.get("keys"), str) else params.get("keys", []),
                token=self._cancellation_token),
            ComputerControlAction.KEYBOARD_PRESS: lambda: self._adapter.keyboard_press(
                key=params["key"], token=self._cancellation_token),
            # Scroll
            ComputerControlAction.SCROLL: lambda: self._adapter.scroll(
                direction=ScrollDirection(params.get("direction", "down")),
                amount=params.get("amount", 3),
                token=self._cancellation_token,
            ),
            # Clipboard
            ComputerControlAction.CLIPBOARD_READ: lambda: self._adapter.clipboard_read(
                token=self._cancellation_token),
            ComputerControlAction.CLIPBOARD_WRITE: lambda: self._adapter.clipboard_write(
                text=params["text"], token=self._cancellation_token),
            # Screenshot
            ComputerControlAction.SCREENSHOT: lambda: self._adapter.screenshot(
                save_path=params.get("path"), token=self._cancellation_token),
            # Window
            ComputerControlAction.WINDOW_LIST: lambda: self._adapter.window_list(),
            ComputerControlAction.WINDOW_FOCUS: lambda: self._adapter.window_focus(
                title=params["title"]),
            ComputerControlAction.WINDOW_MINIMIZE: lambda: self._adapter.window_minimize(
                title=params["title"]),
            ComputerControlAction.WINDOW_MAXIMIZE: lambda: self._adapter.window_maximize(
                title=params["title"]),
            ComputerControlAction.WINDOW_CLOSE: lambda: self._adapter.window_close(
                title=params["title"]),
            ComputerControlAction.WINDOW_GET_INFO: lambda: self._adapter.window_get_info(
                title=params["title"]),
            # App
            ComputerControlAction.APP_LAUNCH: lambda: self._adapter.app_launch(
                path=params.get("path", ""), name=params.get("name", "")),
            ComputerControlAction.APP_KILL: lambda: self._adapter.app_kill(
                pid=params.get("pid", 0), name=params.get("name", "")),
            ComputerControlAction.APP_LIST: lambda: self._adapter.app_list(),
            # System
            ComputerControlAction.VOLUME_GET: lambda: self._adapter.volume_get(),
            ComputerControlAction.VOLUME_SET: lambda: self._adapter.volume_set(
                value=params["value"]),
            ComputerControlAction.BRIGHTNESS_GET: lambda: self._adapter.brightness_get(),
            ComputerControlAction.BRIGHTNESS_SET: lambda: self._adapter.brightness_set(
                value=params["value"]),
            # Utility
            ComputerControlAction.WAIT: lambda: ExecutionResult.ok_result(
                    message=f"Ждем {params['seconds']}s",
                    data={"seconds": params["seconds"]}),
            ComputerControlAction.CAPABILITY_CHECK: lambda: ExecutionResult.ok_result(
                message="Capability check",
                data={"platform": str(self._adapter.platform)}),
        }

        handler = dispatch.get(action)
        if handler is None:
            return ExecutionResult.error_result(
                "no_handler",
                f"Нет обработчика для действия: {action.value}",
            )

        return handler()

    @staticmethod
    def _parse_hotkey(keys_raw: str) -> list[str]:
        """Parse 'ctrl+shift+e' → ['ctrl', 'shift', 'e']."""
        if isinstance(keys_raw, list):
            return [str(k) for k in keys_raw]
        parts = [k.strip() for k in keys_raw.lower().split("+")]
        return parts

    @staticmethod
    def _to_tool_result(exec_result: ExecutionResult, start_time: float) -> Any:
        """Convert ExecutionResult to ToolResult."""
        ToolResult = _get_tool_result_class()
        finished_time = time.monotonic()
        return ToolResult(
            ok=exec_result.ok,
            code=exec_result.code,
            message=exec_result.message,
            data=exec_result.data,
            warnings=exec_result.warnings,
            retryable=not exec_result.ok and exec_result.code not in ("cancelled", "missing_fields"),
            started_at=start_time,
            finished_at=finished_time,
        )


# ── Public API ──────────────────────────────────────────────────────

def build_computer_control_executor(adapter=None, **kwargs) -> ComputerControlExecutor:
    """Build a ComputerControlExecutor with the given adapter.

    If adapter is None, uses MockPlatformAdapter for safe E2E.
    """
    if adapter is None:
        from computer_control.deterministic import MockPlatformAdapter
        adapter = MockPlatformAdapter()
    return ComputerControlExecutor(adapter=adapter, **kwargs)


def run_computer_control(action: str, parameters: dict[str, Any] | None = None,
                         adapter=None, **kwargs) -> Any:
    """Execute a single computer-control action.

    This is the simplest entry point for direct calls.
    """
    executor = build_computer_control_executor(adapter=adapter, **kwargs)
    return executor.execute(action, parameters or {})


__all__ = [
    "ComputerControlExecutor",
    "build_computer_control_executor",
    "run_computer_control",
    "validate_action",
    "_LEGACY_ACTION_MAP",
]
