"""Typed desktop ops: closed set, injected backends, no exec sandbox."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from actions.desktop import (
    DesktopBackends,
    DesktopDeniedError,
    UnknownDesktopOpError,
    desktop_control,
)
from acta.safety import DecisionKind, RiskLevel, UntrustedSource, authorize, risk_for


class FakeMouse:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def click(self, x: int, y: int, button: str = "left") -> str:
        self.calls.append(("click", x, y, button))
        return "clicked"


class FakeKeyboard:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def type(self, text: str) -> str:
        self.calls.append(("type", text))
        return "typed"

    def shortcut(self, keys: str | list[str]) -> str:
        self.calls.append(("shortcut", keys))
        return "shortcut"


class FakeWindow:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def activate(self, title: str) -> str:
        self.calls.append(("activate", title))
        return "activated"


class FakeScreen:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def capture(self, path: str | None = None) -> str:
        self.calls.append(("capture", path))
        return path or "screenshot.png"


class FakeCopy:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.deleted: list[object] = []

    def copy(self, source: str, destination: str) -> str:
        self.calls.append(("copy", source, destination))
        return "copied"

    def delete(self, *args: object, **kwargs: object) -> None:
        self.deleted.append((args, kwargs))
        raise AssertionError("file.copy must not delete")


def _backends(
    mouse: FakeMouse | None = None,
    keyboard: FakeKeyboard | None = None,
    window: FakeWindow | None = None,
    screen: FakeScreen | None = None,
    copy: FakeCopy | None = None,
) -> tuple[DesktopBackends, FakeMouse, FakeKeyboard, FakeWindow, FakeScreen, FakeCopy]:
    mouse = mouse or FakeMouse()
    keyboard = keyboard or FakeKeyboard()
    window = window or FakeWindow()
    screen = screen or FakeScreen()
    copy = copy or FakeCopy()
    return (
        DesktopBackends(
            mouse=mouse,
            keyboard=keyboard,
            window=window,
            screen=screen,
            copy=copy,
        ),
        mouse,
        keyboard,
        window,
        screen,
        copy,
    )


def test_module_has_no_exec_or_eval() -> None:
    source = Path(desktop_control.__code__.co_filename).read_text(encoding="utf-8")
    assert "exec(" not in source
    assert "eval(" not in source
    assert "compile(" not in source
    assert "_execute_generated_code" not in source
    assert "_ask_gemini_for_desktop_action" not in source
    assert "_build_sandbox" not in source
    assert "or_client" not in source


def test_risk_for_desktop_control_is_confirm() -> None:
    assert risk_for("desktop_control") is RiskLevel.CONFIRM
    assert int(risk_for("desktop_control")) == 2


def test_typed_mutating_ops_are_confirm_and_reads_are_read() -> None:
    for op in (
        "mouse.click",
        "keyboard.type",
        "keyboard.shortcut",
        "window.activate",
        "file.copy",
    ):
        by_op = authorize(
            "desktop_control",
            {"op": op},
            source=UntrustedSource.USER,
        )
        by_action = authorize(
            "desktop_control",
            {"action": op},
            source=UntrustedSource.USER,
        )
        assert by_op.kind is DecisionKind.CONFIRM
        assert by_action.kind is DecisionKind.CONFIRM
        assert by_op.risk is RiskLevel.CONFIRM

    for op in ("list", "stats", "screen.capture"):
        decision = authorize(
            "desktop_control",
            {"op": op},
            source=UntrustedSource.USER,
        )
        assert decision.kind is DecisionKind.ALLOW
        assert decision.risk is RiskLevel.READ


def test_unknown_op_does_not_execute() -> None:
    backends, mouse, keyboard, window, screen, copy = _backends()
    with pytest.raises(UnknownDesktopOpError) as exc_info:
        desktop_control(
            parameters={"op": "shell.run", "code": "print(1)"},
            backends=backends,
        )
    assert exc_info.value.field == "op"
    assert mouse.calls == []
    assert keyboard.calls == []
    assert window.calls == []
    assert screen.calls == []
    assert copy.calls == []
    assert copy.deleted == []


def test_unknown_action_and_empty_op_do_not_execute() -> None:
    backends, mouse, *_rest = _backends()
    with pytest.raises(UnknownDesktopOpError):
        desktop_control(
            parameters={"action": "task", "task": "click"},
            backends=backends,
        )
    with pytest.raises(UnknownDesktopOpError):
        desktop_control(parameters={}, backends=backends)
    assert mouse.calls == []


def test_mouse_click_uses_injected_backend() -> None:
    backends, mouse, keyboard, window, screen, copy = _backends()
    result = desktop_control(
        parameters={"op": "mouse.click", "x": 10, "y": 20, "button": "right"},
        player=None,
        backends=backends,
    )
    assert result == "clicked"
    assert mouse.calls == [("click", 10, 20, "right")]
    assert keyboard.calls == []
    assert window.calls == []
    assert screen.calls == []
    assert copy.calls == []


def test_keyboard_type_uses_injected_backend() -> None:
    backends, mouse, keyboard, *_rest = _backends()
    result = desktop_control(
        parameters={"action": "keyboard.type", "text": "hello"},
        backends=backends,
    )
    assert result == "typed"
    assert keyboard.calls == [("type", "hello")]
    assert mouse.calls == []


def test_keyboard_shortcut_uses_injected_backend() -> None:
    backends, _mouse, keyboard, *_rest = _backends()
    result = desktop_control(
        parameters={"op": "keyboard.shortcut", "keys": "command+c"},
        backends=backends,
    )
    assert result == "shortcut"
    assert keyboard.calls == [("shortcut", "command+c")]


def test_window_activate_uses_injected_backend() -> None:
    backends, _mouse, _keyboard, window, *_rest = _backends()
    result = desktop_control(
        parameters={"op": "window.activate", "title": "Safari"},
        backends=backends,
    )
    assert result == "activated"
    assert window.calls == [("activate", "Safari")]


def test_screen_capture_uses_injected_backend() -> None:
    backends, _mouse, _keyboard, _window, screen, copy = _backends()
    result = desktop_control(
        parameters={"op": "screen.capture", "path": "/tmp/shot.png"},
        backends=backends,
    )
    assert result == "/tmp/shot.png"
    assert screen.calls == [("capture", "/tmp/shot.png")]
    assert copy.calls == []


def test_file_copy_uses_injected_backend() -> None:
    backends, _mouse, _keyboard, _window, _screen, copy = _backends()
    result = desktop_control(
        parameters={
            "op": "file.copy",
            "src": "/tmp/a.txt",
            "destination": "/tmp/b.txt",
        },
        backends=backends,
    )
    assert result == "copied"
    assert copy.calls == [("copy", "/tmp/a.txt", "/tmp/b.txt")]
    assert copy.deleted == []


def test_file_copy_default_backend_does_not_delete(tmp_path: Path) -> None:
    src = tmp_path / "note.txt"
    dest = tmp_path / "copy.txt"
    src.write_text("keep me", encoding="utf-8")
    result = desktop_control(
        parameters={"op": "file.copy", "src": str(src), "destination": str(dest)},
        backends=DesktopBackends(),
    )
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "keep me"
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "keep me"
    assert "Copied" in result


def test_file_copy_refuses_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("new", encoding="utf-8")
    dest.write_text("old", encoding="utf-8")
    result = desktop_control(
        parameters={"op": "file.copy", "src": str(src), "destination": str(dest)},
        backends=DesktopBackends(),
    )
    assert dest.read_text(encoding="utf-8") == "old"
    assert src.exists()
    assert "already exists" in result


def test_untrusted_source_does_not_run_mutating_op() -> None:
    backends, mouse, _keyboard, _window, _screen, copy = _backends()
    with pytest.raises(DesktopDeniedError) as exc_info:
        desktop_control(
            parameters={"op": "mouse.click", "x": 1, "y": 2},
            backends=backends,
            source=UntrustedSource.WEB,
        )
    assert exc_info.value.decision.kind is DecisionKind.DENY
    assert mouse.calls == []
    assert copy.calls == []


def test_list_and_stats_use_injected_desktop(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    listed = desktop_control(
        parameters={"action": "list"},
        desktop_dir=tmp_path,
    )
    stats = desktop_control(
        parameters={"op": "stats"},
        desktop_dir=tmp_path,
    )
    assert "a.txt" in listed
    assert "folder" in listed
    assert "Files   : 1" in stats
    assert "Folders : 1" in stats


def test_or_client_is_not_imported_on_happy_path() -> None:
    sys.modules.pop("or_client", None)
    backends, mouse, *_rest = _backends()
    desktop_control(
        parameters={"op": "mouse.click", "x": 3, "y": 4},
        player=None,
        backends=backends,
    )
    assert mouse.calls == [("click", 3, 4, "left")]
    assert "or_client" not in sys.modules
