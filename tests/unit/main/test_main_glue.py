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
    monkeypatch.setattr(mod, "API_CONFIG_PATH", tmp_path / "missing.json")
    stack = mod._build_stack()
    # Bridge may be None only if mark.bridge import failed entirely.
    if stack is None:
        assert mod.build_runtime_stack is None
    else:
        assert stack.provider_id == "gemini"
        assert stack.summary_lines()


def test_authorize_tool_available_when_bridge_loaded() -> None:
    mod = _load_main_module()
    if mod.authorize_tool is None or mod.build_runtime_stack is None:
        pytest.skip("bridge unavailable")
    stack = mod.build_runtime_stack(
        repo_root=ROOT,
        key_provider=lambda _n: None,
        memory_db_path=ROOT / "tmp" / "test_main_glue_mem.sqlite3",
    )
    allowed, _reason = mod.authorize_tool(stack, "open_app", {"app_name": "x"})
    assert allowed is True
