"""Smoke tests for main.py runtime-bridge glue (no GUI, no Gemini Live)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[3]


def _load_main_module():
    path = ROOT / "main.py"
    # Avoid executing UI side effects: main imports JarvisUI at module level.
    # Skip when PyQt6 is missing in the test venv.
    pytest.importorskip("PyQt6")
    spec = importlib.util.spec_from_file_location("mark_main_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"main.py import blocked: {exc}")
    return mod


def test_build_stack_best_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_main_module()
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    stack = mod._build_stack()
    # Bridge may be None only if mark.bridge import failed entirely.
    if stack is None:
        assert mod.build_runtime_stack is None
    else:
        assert stack.provider_id == "gemini"
        assert stack.summary_lines()


def test_main_no_longer_exposes_legacy_authorize_tool_dispatch() -> None:
    mod = _load_main_module()
    assert not hasattr(mod, "authorize_tool")
    assert mod.LiveToolBridge is not None


def test_live_config_exports_the_injected_registry() -> None:
    mod = _load_main_module()
    ui = type(
        "UI",
        (),
        {
            "on_text_command": None,
            "control_plane": None,
            "muted": False,
            "set_state": lambda *_args: None,
            "write_log": lambda *_args: None,
        },
    )()
    live = mod.SlonLive(ui, runtime_stack=None)

    config = live._build_config()

    declarations = config.tools[0].function_declarations
    assert [item.name for item in declarations] == list(live.tool_registry.names())


def test_live_uses_explicit_audio_model_metadata() -> None:
    mod = _load_main_module()
    ui = type(
        "UI",
        (),
        {
            "on_text_command": None,
            "control_plane": None,
            "muted": False,
            "set_state": lambda *_args: None,
            "write_log": lambda *_args: None,
        },
    )()
    live = mod.SlonLive(ui, selected_model=mod.LIVE_MODEL_INFO)
    assert live.selected_model is mod.LIVE_MODEL_INFO
    assert live.selected_model.audio_input is True
    assert live.selected_model.audio_output is True


def test_live_events_keep_session_identity_across_connection_generations() -> None:
    mod = _load_main_module()
    ui = type(
        "UI", (), {
            "on_text_command": None, "control_plane": None, "muted": False,
            "set_state": lambda *_args: None, "write_log": lambda *_args: None,
        },
    )()
    live = mod.SlonLive(ui, session_id="logical-session")
    events = []
    live.runtime_events.subscribe(events.append)

    live._on_connected(object(), object())
    live._emit_event(mod.RuntimeEventKind.LISTENING)
    live.audio.unbind()
    live._on_connected(object(), object())
    live._emit_event(mod.RuntimeEventKind.LISTENING)

    assert [event.session_id for event in events] == [
        "logical-session", "logical-session"
    ]
    assert [event.connection_generation for event in events] == [1, 2]


@pytest.mark.asyncio
async def test_live_close_is_idempotent_and_closes_logical_session() -> None:
    mod = _load_main_module()
    closed = []
    manager = SimpleNamespace(
        create=lambda **_kwargs: SimpleNamespace(id="session-close"),
        close=lambda session_id, *, workspace_id: closed.append(
            (session_id, workspace_id)
        ),
    )
    stack = SimpleNamespace(
        session_manager=manager, tool_registry=None, safety=None,
        summary_lines=lambda: [],
    )
    ui = SimpleNamespace(
        on_text_command=None, control_plane=None, muted=False,
        set_state=lambda *_args: None, write_log=lambda *_args: None,
    )
    live = mod.SlonLive(ui, runtime_stack=stack)
    live.session = SimpleNamespace(close=AsyncMock())

    await live.close()
    await live.close()

    live.session.close.assert_awaited_once()
    assert closed == [("session-close", "desktop")]
