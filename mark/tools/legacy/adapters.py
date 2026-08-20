"""Thin adapters from canonical tool arguments to legacy Slon actions.

Imports deliberately happen at execution time.  Several legacy action modules
load optional desktop automation packages, and merely building a tool registry
must remain safe in headless/offline environments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from pathlib import Path
from typing import Any

from mark.tools.contracts import ToolResult


LegacyHandler = Callable[[Mapping[str, object]], ToolResult]


def with_legacy_speak(
    handler: Callable[[Mapping[str, object]], object],
    speak: Callable[..., object] | None,
) -> Callable[[Mapping[str, object]], object]:
    """Bind one compatibility callback without adding it to model arguments."""
    if speak is None or not getattr(handler, "_accepts_legacy_context", False):
        return handler

    def contextual_handler(args: Mapping[str, object]) -> object:
        return handler(args, _speak=speak)  # type: ignore[call-arg]

    return contextual_handler


def with_legacy_context(
    handler: Callable[[Mapping[str, object]], object],
    *,
    speak: Callable[..., object] | None = None,
    player: object | None = None,
) -> Callable[[Mapping[str, object]], object]:
    """Bind legacy UI callbacks at composition time, outside model arguments."""
    if not getattr(handler, "_accepts_legacy_context", False):
        return handler

    def contextual_handler(args: Mapping[str, object]) -> object:
        return handler(args, _speak=speak, _player=player)  # type: ignore[call-arg]

    return contextual_handler


def normalize_legacy_result(result: object) -> ToolResult:
    """Convert the result conventions used by ``actions/*`` to ``ToolResult``."""
    if isinstance(result, ToolResult):
        return result
    if result is None:
        return ToolResult(ok=True, code="legacy.ok")
    if isinstance(result, str):
        return ToolResult(ok=True, code="legacy.ok", message=result)
    if isinstance(result, dict):
        return ToolResult(ok=True, code="legacy.ok", data=result)
    if isinstance(result, bool):
        return ToolResult(
            ok=result,
            code="legacy.ok" if result else "legacy.failed",
            data=result,
        )
    # Preserve opaque legacy values as data. Adapters with a real failure
    # convention must translate it explicitly instead of claiming success.
    return ToolResult(ok=True, code="legacy.ok", data=result)


def _action_handler(
    module_name: str,
    function_name: str,
    *,
    accepts_speak: bool = False,
) -> LegacyHandler:
    def handler(
        args: Mapping[str, object], *, _speak: Callable[..., object] | None = None,
        _player: object | None = None,
    ) -> ToolResult:
        action = getattr(import_module(module_name), function_name)
        kwargs: dict[str, Any] = {"parameters": dict(args), "player": _player}
        if accepts_speak:
            kwargs["speak"] = _speak
        return normalize_legacy_result(action(**kwargs))

    handler.__name__ = f"{function_name}_handler"
    handler._accepts_legacy_context = True  # type: ignore[attr-defined]
    return handler


open_app_handler = _action_handler("actions.open_app", "open_app")
web_search_handler = _action_handler("actions.web_search", "web_search")
browser_control_handler = _action_handler("actions.browser_control", "browser_control")
file_controller_handler = _action_handler("actions.file_controller", "file_controller")
desktop_control_handler = _action_handler("actions.desktop", "desktop_control")
computer_control_handler = _action_handler(
    "actions.computer_control", "computer_control"
)
computer_settings_handler = _action_handler(
    "actions.computer_settings", "computer_settings"
)
cmd_control_handler = _action_handler("actions.cmd_control", "cmd_control")
screen_process_handler = _action_handler("actions.screen_processor", "screen_process")
reminder_handler = _action_handler("actions.reminder", "reminder")
weather_report_handler = _action_handler("actions.weather_report", "weather_action")
flight_finder_handler = _action_handler(
    "actions.flight_finder", "flight_finder", accepts_speak=True
)
youtube_video_handler = _action_handler(
    "actions.youtube_video", "youtube_video", accepts_speak=True
)
file_processor_handler = _action_handler(
    "actions.file_processor", "file_processor", accepts_speak=True
)
game_updater_handler = _action_handler(
    "actions.game_updater", "game_updater", accepts_speak=True
)
send_message_handler = _action_handler("actions.send_message", "send_message")
code_helper_handler = _action_handler(
    "actions.code_helper", "code_helper", accepts_speak=True
)
dev_agent_handler = _action_handler(
    "actions.dev_agent", "dev_agent", accepts_speak=True
)


def read_file_handler(args: Mapping[str, object]) -> ToolResult:
    """Canonical narrow read helper used by the iterative agent runtime."""
    try:
        content = Path(str(args["path"])).read_text(encoding="utf-8")
    except (OSError, UnicodeError, KeyError) as exc:
        return ToolResult(ok=False, code="read_error", message=str(exc))
    return ToolResult(ok=True, code="ok", data=content)


def agent_task_handler(args: Mapping[str, object]) -> ToolResult:
    """Preserve the existing asynchronous task-queue bridge from ``main.py``."""
    task_queue = import_module("agent.task_queue")
    priority_value = args.get("priority", "normal")
    priority_name = (
        priority_value.lower() if isinstance(priority_value, str) else "normal"
    )
    priority_map = {
        "low": task_queue.TaskPriority.LOW,
        "normal": task_queue.TaskPriority.NORMAL,
        "high": task_queue.TaskPriority.HIGH,
    }
    task_id = task_queue.get_queue().submit(
        goal=str(args.get("goal", "")),
        priority=priority_map.get(priority_name, task_queue.TaskPriority.NORMAL),
        speak=None,
    )
    return normalize_legacy_result(f"Task started (ID: {task_id}).")


LEGACY_HANDLERS: Mapping[str, LegacyHandler] = {
    "read_file": read_file_handler,
    "open_app": open_app_handler,
    "web_search": web_search_handler,
    "browser_control": browser_control_handler,
    "file_controller": file_controller_handler,
    "desktop_control": desktop_control_handler,
    "computer_control": computer_control_handler,
    "computer_settings": computer_settings_handler,
    "cmd_control": cmd_control_handler,
    "screen_process": screen_process_handler,
    "reminder": reminder_handler,
    "weather_report": weather_report_handler,
    "flight_finder": flight_finder_handler,
    "youtube_video": youtube_video_handler,
    "file_processor": file_processor_handler,
    "game_updater": game_updater_handler,
    "send_message": send_message_handler,
    "code_helper": code_helper_handler,
    "dev_agent": dev_agent_handler,
    "agent_task": agent_task_handler,
}


__all__ = [
    "LEGACY_HANDLERS",
    "LegacyHandler",
    "agent_task_handler",
    "normalize_legacy_result",
    "with_legacy_context",
    "with_legacy_speak",
]
