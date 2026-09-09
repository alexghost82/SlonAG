"""Adversarial cwd, timeout, output, and symlink tests for hardened shell_exec."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from acta.safety.errors import ArgValidationError
from acta.tools.legacy import LEGACY_HANDLERS
from actions.shell_exec import _safe_cwd, shell_exec


def test_tmp_prefix_is_not_startswith() -> None:
    with pytest.raises(ArgValidationError):
        _safe_cwd("/tmpx", str(Path.cwd()))


def test_foreign_home_rejected() -> None:
    foreign = "/Users/NotTheCurrentSlonUser"
    with pytest.raises(ArgValidationError):
        _safe_cwd(foreign, str(Path.cwd()))


def test_parent_traversal_rejected() -> None:
    with pytest.raises(ArgValidationError):
        _safe_cwd("/etc/../etc", str(Path.cwd()))


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    link = tmp_path / "escape"
    target = Path("/etc")
    if not target.is_dir():
        pytest.skip("/etc is not a directory on this platform")
    link.symlink_to(target)
    with pytest.raises(ArgValidationError):
        _safe_cwd(str(link), str(Path.cwd()))


def test_any_existing_dir_is_not_enough(tmp_path: Path) -> None:
    # tmp_path is approved (under gettempdir). Use a dir that exists but is
    # outside home/tmp — /etc or /System.
    outsider = Path("/etc")
    if not outsider.is_dir():
        pytest.skip("no outsider directory")
    with pytest.raises(ArgValidationError):
        _safe_cwd(str(outsider), str(Path.cwd()))


def test_timeout_sets_timed_out_and_returns() -> None:
    started = time.monotonic()
    result = shell_exec(
        {"command": "sleep 20", "timeout": 1, "kill_tree": True},
        current_cwd=str(Path.home()),
    )
    elapsed = time.monotonic() - started
    assert result.ok is False
    assert result.code == "timeout"
    assert isinstance(result.data, dict)
    assert result.data.get("timed_out") is True
    assert elapsed < 8


def test_timeout_without_kill_tree_does_not_hang() -> None:
    started = time.monotonic()
    result = shell_exec(
        {"command": "sleep 20", "timeout": 1, "kill_tree": False},
        current_cwd=str(Path.home()),
    )
    elapsed = time.monotonic() - started
    assert result.code == "timeout"
    assert isinstance(result.data, dict)
    assert result.data.get("timed_out") is True
    assert elapsed < 8


def test_huge_stdout_is_truncated() -> None:
    payload = "A" * 200_000
    result = shell_exec(
        {"arguments": ["echo", payload], "stdout_max": 64},
        current_cwd=str(Path.home()),
    )
    assert result.ok is True
    assert isinstance(result.data, dict) or "A" in result.message
    assert len(result.message.encode("utf-8")) < 10_000


def test_registered_handler_rejects_tmpx() -> None:
    result = LEGACY_HANDLERS["shell_exec"]({"command": "echo x", "cwd": "/tmpx"})
    assert result.ok is False
    assert result.code in {"invalid_cwd", "invalid_args"}


def test_no_run_until_complete_in_source() -> None:
    import actions.shell_exec as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    assert "run_until_complete(" not in text


def test_dev_agent_and_settings_have_no_shell_true() -> None:
    root = Path(__file__).resolve().parents[2]
    for rel in ("actions/dev_agent.py", "actions/computer_settings.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "shell=True" not in text


def test_tempfile_root_is_allowed() -> None:
    tmp = Path(tempfile.gettempdir()).resolve()
    cwd = _safe_cwd(str(tmp), str(Path.cwd()))
    assert cwd == tmp
    # Keep HOME in env for readability of failures; do not trust it for roots.
    assert os.environ.get("HOME")
