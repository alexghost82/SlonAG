from __future__ import annotations

from acta.bridge.control_plane import ControlPlaneUnavailable, DesktopControlPlane
from runtime.commands import REQUIRED_COMMANDS, UiCommand, UiCommandKind
from runtime.events import RuntimeEventKind


def test_required_command_catalog() -> None:
    assert REQUIRED_COMMANDS == {
        "send_message",
        "start_voice",
        "stop_voice",
        "cancel",
        "approve",
        "deny",
        "select_model",
        "change_settings",
        "open_session",
    }


def test_required_event_catalog() -> None:
    values = {item.value for item in RuntimeEventKind}
    for required in {
        "assistant_text",
        "thinking",
        "listening",
        "speaking",
        "tool_started",
        "tool_finished",
        "approval_required",
        "job_progress",
        "error",
        "session_changed",
    }:
        assert required in values


def test_control_plane_dispatches_typed_commands() -> None:
    plane = DesktopControlPlane()
    seen: list[str] = []
    plane.bind_text_handler(lambda text: seen.append(text) or "ok")  # type: ignore[func-returns-value]
    plane.bind_command("cancel", lambda: seen.append("cancel"))
    plane.bind_command("start_voice", lambda: seen.append("start"))
    assert plane.dispatch(UiCommand(UiCommandKind.SEND_MESSAGE, {"text": "hi"})) == "ok"
    plane.dispatch(UiCommand(UiCommandKind.CANCEL))
    plane.dispatch(UiCommand(UiCommandKind.START_VOICE))
    assert seen == ["hi", "cancel", "start"]
    try:
        plane.dispatch(UiCommand(UiCommandKind.STOP_VOICE))
        raise AssertionError("missing handler must fail closed")
    except ControlPlaneUnavailable:
        pass
