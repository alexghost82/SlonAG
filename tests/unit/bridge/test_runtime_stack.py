"""Unit tests for mark.bridge runtime assembly (no UI, no network)."""

from __future__ import annotations

from pathlib import Path

from mark.bridge import authorize_tool, build_runtime_stack


def test_build_stack_degrades_without_keys(tmp_path: Path) -> None:
    stack = build_runtime_stack(
        repo_root=tmp_path,
        provider_id="gemini",
        network_mode="offline",
        key_provider=lambda _name: None,
        memory_db_path=tmp_path / "mem.sqlite3",
    )
    assert stack.provider_id == "gemini"
    assert stack.network_mode == "offline"
    assert stack.safety is not None
    assert stack.network is not None
    assert stack.memory is not None
    assert any("provider_id=gemini" in line for line in stack.status_lines)
    # Router may construct even without keys; validate is separate.
    assert stack.router is not None or any(
        "router:" in line for line in stack.status_lines
    )


def test_authorize_unknown_tool_legacy_allow(tmp_path: Path) -> None:
    stack = build_runtime_stack(
        repo_root=tmp_path,
        memory_db_path=tmp_path / "m.sqlite3",
        key_provider=lambda _n: None,
    )
    allowed, reason = authorize_tool(stack, "open_app", {"app_name": "Safari"})
    assert allowed is True
    assert reason


def test_authorize_without_safety() -> None:
    from mark.bridge import RuntimeStack

    stack = RuntimeStack(provider_id="gemini", network_mode="hybrid", safety=None)
    allowed, reason = authorize_tool(stack, "anything", {})
    assert allowed is True
    assert "legacy allow" in reason
