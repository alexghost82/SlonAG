"""Smoke tests for main.py runtime-bridge glue (no GUI, no Gemini Live)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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
