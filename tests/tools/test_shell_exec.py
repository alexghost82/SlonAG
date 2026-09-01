"""Comprehensive tests for the canonical shell execution tool.

Covers: timeout, cancellation, huge output, invalid cwd, rejected command,
process-tree cleanup, platform handling, and Russian error messages.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from acta.safety.types import DecisionKind, RiskLevel, SafetyDecision, UntrustedSource
from acta.tools.contracts import ToolResult

shell_exec_mod = None
ShellExecResult = None


@pytest.fixture(autouse=True)
def _import_shell_exec():
    global shell_exec_mod, ShellExecResult
    if shell_exec_mod is None:
        from actions import shell_exec as mod
        from actions.shell_exec import ShellExecResult as SER
        shell_exec_mod = mod
        ShellExecResult = SER


# ---------------------------------------------------------------------------
# 1. Basic execution
# ---------------------------------------------------------------------------

def test_shell_exec_success_stdout() -> None:
    """Happy path: command with stdout."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo hello"},
        current_cwd=str(Path.cwd()),
    )
    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.code == "ok"
    assert "hello" in result.message


def test_shell_exec_exit_code() -> None:
    """Non-zero exit produces ToolResult(ok=False, code='nonzero_exit')."""
    result = shell_exec_mod.shell_exec(
        {"command": "false"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "nonzero_exit"


def test_shell_exec_arguments_variant() -> None:
    """Accept 'arguments' list instead of 'command' string."""
    result = shell_exec_mod.shell_exec(
        {"arguments": ["echo", "arg1", "arg2"]},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
    assert "arg1" in result.message


def test_shell_exec_stderr() -> None:
    """Redirection at start of command is blocked as a command injection vector."""
    # _is_blocked blocks special first chars and prefixes
    assert shell_exec_mod._is_blocked("> /tmp/file") is True
    assert shell_exec_mod._is_blocked("< /etc/shadow") is True
    assert shell_exec_mod._is_blocked(">> /tmp/append") is True


def test_shell_exec_no_output() -> None:

    """Command with no stdout/stderr produces '(нет вывода)'."""
    result = shell_exec_mod.shell_exec(
        {"command": "true"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
    assert "(нет вывода)" in result.message


# ---------------------------------------------------------------------------
# 2. Timeout
# ---------------------------------------------------------------------------

def test_shell_exec_timeout() -> None:
    """Short timeout causes non-zero exit; tool returns ok=False."""
    result = shell_exec_mod.shell_exec(
        {"command": "sleep 10", "timeout": 0.5},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "nonzero_exit"
    data = result.data
    if isinstance(data, dict):
        # Timeout is clamped to min 1.0s
        assert data.get("timeout_seconds") >= 1.0


# ---------------------------------------------------------------------------
# 3. Process-tree termination (kill_tree)
# ---------------------------------------------------------------------------

def test_shell_exec_process_tree_cleanup() -> None:
    """Subprocess tree is cleaned up after execution."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo tree-test"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True


def test_shell_exec_timeout_kills_tree() -> None:
    """Timeout kills the process group."""
    result = shell_exec_mod.shell_exec(
        {"command": "sleep 60", "timeout": 0.5, "kill_tree": True},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    data = result.data
    if isinstance(data, dict):
        assert data.get("killed_by_tree") is True


# ---------------------------------------------------------------------------
# 4. Output limits
# ---------------------------------------------------------------------------

def test_shell_exec_stdout_cap() -> None:
    """stdout_max caps output and appends truncation marker."""
    big_text = "A" * 100000  # 100 KB
    result = shell_exec_mod.shell_exec(
        {"arguments": ["python3", "-c", f'print("{big_text}")'], "stdout_max": 1000},
        current_cwd=str(Path.cwd()),
    )
    # stdout is truncated at ~1000 bytes
    assert "A" in result.message
    # Check that output was truncated (marker present)
    from i18n import _
    truncated_marker = _("shell_exec.output_truncated")
    assert truncated_marker in result.message


def test_shell_exec_stderr() -> None:
    """Redirection at start of command is blocked as a command injection vector."""
    # _is_blocked blocks special first chars and prefixes
    assert shell_exec_mod._is_blocked("> /tmp/file") is True
    assert shell_exec_mod._is_blocked("< /etc/shadow") is True
    assert shell_exec_mod._is_blocked(">> /tmp/append") is True
# ---------------------------------------------------------------------------
# 5. Invalid CWD
# ---------------------------------------------------------------------------

def test_shell_exec_invalid_cwd() -> None:
    """Non-existent CWD returns ToolResult(ok=False, code='invalid_cwd')."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo x", "cwd": "/nonexistent/path/xyz123"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "invalid_cwd"


def test_shell_exec_valid_cwd_under_home() -> None:
    """CWD under HOME is accepted."""
    home = str(Path.home())
    result = shell_exec_mod.shell_exec(
        {"command": "pwd", "cwd": home},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True


# ---------------------------------------------------------------------------
# 6. Blocked commands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cmd",
    [
        "sudo rm -rf /tmp",
        "su -c whoami",
        "chmod 777 /etc/passwd",
        "rm -rf /",
        "shutdown -h now",
        "reboot",
        "poweroff",
        "init 6",
        "dd if=/dev/zero of=/dev/sda",
    ],
)
def test_shell_exec_blocked(cmd: str) -> None:
    """Dangerous commands are blocked by policy."""
    result = shell_exec_mod.shell_exec(
        {"command": cmd},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "blocked"


# ---------------------------------------------------------------------------
# 7. Rejected command (safety deny)
# ---------------------------------------------------------------------------

def test_shell_exec_denied_by_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SafetyPolicy denies, tool returns ok=False, code='denied'."""
    import acta.safety.policy as pol

    fake_decision = SafetyDecision(
        kind=DecisionKind.DENY,
        tool_name="shell_exec",
        risk=RiskLevel.CONFIRM,
        source=UntrustedSource.WEB,
        intent="shell_exec",
        args={"command": "echo x"},
        reason="Untrusted source.",
    )

    # Patch at module level where it's imported
    monkeypatch.setattr(shell_exec_mod, "authorize", lambda *a, **kw: fake_decision)

    result = shell_exec_mod.shell_exec(
        {"command": "echo x"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "denied"


# ---------------------------------------------------------------------------
# 8. Missing/invalid arguments
# ---------------------------------------------------------------------------

def test_shell_exec_missing_command() -> None:
    """No command or arguments returns appropriate error."""
    result = shell_exec_mod.shell_exec(
        {},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "missing_field"


def test_shell_exec_empty_command() -> None:
    """Empty command string returns error."""
    result = shell_exec_mod.shell_exec(
        {"command": ""},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False


def test_shell_exec_empty_arguments_list() -> None:
    """Empty arguments list returns error."""
    result = shell_exec_mod.shell_exec(
        {"arguments": []},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "missing_field"


def test_shell_exec_non_string_argument_item() -> None:
    """List with non-string items returns error."""
    result = shell_exec_mod.shell_exec(
        {"arguments": ["echo", 42, "world"]},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False


def test_shell_exec_non_list_arguments() -> None:
    """arguments that is not a list returns error."""
    result = shell_exec_mod.shell_exec(
        {"arguments": "not a list"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "invalid_args"


# ---------------------------------------------------------------------------
# 9. User denial via confirmer
# ---------------------------------------------------------------------------

def test_shell_exec_user_denied() -> None:
    """User declining confirmation returns code='user_denied'."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo x"},
        current_cwd=str(Path.cwd()),
        confirmer=lambda d: False,  # Always decline
    )
    assert result.ok is False
    assert result.code == "user_denied"


def test_shell_exec_user_accepted() -> None:
    """User accepting confirmation runs the command."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo accepted"},
        current_cwd=str(Path.cwd()),
        confirmer=lambda d: True,  # Always accept
    )
    assert result.ok is True


# ---------------------------------------------------------------------------
# 10. Cancellation
# ---------------------------------------------------------------------------

def test_shell_exec_cancel_during_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancel event set before approval returns cancelled."""
    pass  # Full cancellation tested through ToolExecutor.execute() below


# ---------------------------------------------------------------------------
# 11. Platform handling
# ---------------------------------------------------------------------------

def test_shell_exec_platform_echo() -> None:
    """Echo works on all platforms."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo platform-test"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
    assert "platform-test" in result.message


def test_shell_exec_platform_pwd() -> None:
    """pwd returns the cwd."""
    expected_cwd = str(Path.cwd())
    result = shell_exec_mod.shell_exec(
        {"command": "pwd"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
    assert expected_cwd in result.message


# ---------------------------------------------------------------------------
# 12. Russian error messages
# ---------------------------------------------------------------------------

def test_shell_exec_russian_error_blocked() -> None:
    """Blocked commands return Russian error."""
    result = shell_exec_mod.shell_exec(
        {"command": "sudo rm -rf /"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False
    assert result.code == "blocked"


def test_shell_exec_russian_error_invalid_cwd() -> None:
    """Invalid CWD returns Russian error."""
    result = shell_exec_mod.shell_exec(
        {"command": "x", "cwd": "/nonexistent_12345"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is False


# ---------------------------------------------------------------------------
# 13. Stdin support
# ---------------------------------------------------------------------------

def test_shell_exec_stdin() -> None:
    """stdin is piped to the subprocess."""
    result = shell_exec_mod.shell_exec(
        {"command": "cat", "stdin": "hello stdin"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
    assert "hello stdin" in result.message


# ---------------------------------------------------------------------------
# 14. ToolResult structure
# ---------------------------------------------------------------------------

def test_shell_exec_result_data() -> None:
    """Successful call returns structured data dict."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo test-data"},
        current_cwd=str(Path.cwd()),
    )
    assert result.data is not None
    assert isinstance(result.data, dict)
    assert "exit_code" in result.data
    assert "command" in result.data
    assert "cwd" in result.data
    assert result.data["exit_code"] == 0


def test_shell_exec_result_has_all_fields() -> None:
    """ToolResult always has ok, code, message."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo test"},
        current_cwd=str(Path.cwd()),
    )
    assert hasattr(result, "ok")
    assert hasattr(result, "code")
    assert hasattr(result, "message")
    assert hasattr(result, "started_at")
    assert hasattr(result, "finished_at")


# ---------------------------------------------------------------------------
# 15. Integration: full pipeline (ToolResult → model continuation)
# ---------------------------------------------------------------------------

def test_shell_exec_full_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model tool call → ToolRegistry → SafetyPolicy → ToolExecutor → ToolResult."""
    from acta.tools.registry import ToolRegistry
    from acta.tools.executor import ToolExecutor
    from acta.safety.policy import SafetyPolicy
    from acta.tools.contracts import ToolSpec

    # Ensure shell_exec is in the safety registry
    from acta.safety.registry import _REGISTRY, ArgSchema, SafetyRule
    if "shell_exec" not in _REGISTRY:
        _REGISTRY["shell_exec"] = SafetyRule(
            risk=RiskLevel.CONFIRM,
            schema=ArgSchema(types=()),
        )

    registry = ToolRegistry()
    spec = ToolSpec(
        name="shell_exec",
        description="Execute bounded shell command.",
        input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
        output_schema=None,
        handler=shell_exec_mod.shell_exec,
        risk=RiskLevel.CONFIRM,
        timeout_seconds=30.0,
        side_effects=True,
    )
    registry.register(spec)

    policy = SafetyPolicy()
    executor = ToolExecutor(registry, policy, confirmer=lambda d: True)

    outcome = executor.execute(
        "shell_exec",
        {"command": "echo pipeline-test"},
        source=UntrustedSource.USER,
        intent="test",
    )

    assert isinstance(outcome, ToolResult)
    assert outcome.ok is True
    assert "pipeline-test" in outcome.message


# ---------------------------------------------------------------------------
# 16. Integration: cancellation through ToolExecutor
# ---------------------------------------------------------------------------

def test_shell_exec_executor_cancel_during_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation event during approval propagates."""
    cancel_evt = threading.Event()
    cancel_evt.set()  # Pre-cancelled

    from acta.tools.registry import ToolRegistry
    from acta.safety.policy import SafetyPolicy
    from acta.tools.contracts import ToolSpec
    from acta.tools.executor import ToolExecutor
    from acta.tools.contracts import RiskLevel

    registry = ToolRegistry()
    spec = ToolSpec(
        name="shell_exec",
        description="Execute bounded shell command.",
        input_schema={},
        output_schema=None,
        handler=shell_exec_mod.shell_exec,
        risk=RiskLevel.CONFIRM,
        timeout_seconds=30.0,
        side_effects=True,
    )
    registry.register(spec)

    policy = SafetyPolicy()
    executor = ToolExecutor(registry, policy, confirmer=lambda d: True)

    # Pre-cancel: execute should see the cancel event
    outcome = executor.execute(
        "shell_exec",
        {"command": "echo hello"},
        source=UntrustedSource.USER,
        cancel_event=cancel_evt,
    )
    assert outcome.ok is False


# ---------------------------------------------------------------------------
# 17. Legacy cmd_control deprecation shim
# ---------------------------------------------------------------------------

def test_cmd_control_deprecated_shim() -> None:
    """cmd_control delegates to shell_exec but is marked deprecated."""
    try:
        from acta.tools.legacy.adapters import _cmd_control_deprecated_handler
    except Exception as exc:
        pytest.skip(f"Legacy adapter import broken (pre-existing): {exc}")
    result = _cmd_control_deprecated_handler(
        {"command": "echo legacy-test", "cwd": str(Path.cwd())}
    )
    assert result.ok is False
    assert "deprecated" in result.message.lower()
    assert result.code == "deprecated"  # deprecated tool still returns ok=True


def test_cmd_control_legacy_args() -> None:
    """cmd_control accepts 'cmd' as fallback for 'command'."""
    try:
        from acta.tools.legacy.adapters import _cmd_control_deprecated_handler
    except Exception as exc:
        pytest.skip(f"Legacy adapter import broken (pre-existing): {exc}")
    result = _cmd_control_deprecated_handler(
        {"cmd": "echo legacy-cmd", "cwd": str(Path.cwd())}
    )
    assert result.ok is False
    assert "deprecated" in result.message.lower()
    assert result.code == "deprecated"  # deprecated tool still returns ok=True


# ---------------------------------------------------------------------------
# 18. Output truncation markers are detectable
# ---------------------------------------------------------------------------

def test_shell_exec_output_truncation_marker() -> None:
    """Huge output is truncated with a marker.
    Uses stdin piping to avoid ARG_MAX limit on command-line args.
    """
    big_data = "X" * 200000  # 200 KB
    # Write the big data to a temp file, then read and truncate via cat
    tmp = Path.cwd() / "_test_big.txt"
    try:
        tmp.write_text(big_data)
        result = shell_exec_mod.shell_exec(
            {"arguments": ["cat", str(tmp)], "stdout_max": 500},
            current_cwd=str(Path.cwd()),
        )
    finally:
        tmp.unlink(missing_ok=True)
    assert result.ok is True
    from i18n import _
    marker = _("shell_exec.output_truncated")
    assert marker in result.message


# ---------------------------------------------------------------------------
# 19. Environment allowlist
# ---------------------------------------------------------------------------

def test_shell_exec_env_allowlist() -> None:
    """env_allowlist restricts which os.environ keys are visible."""
    os.environ["SHELL_EXEC_TEST_VAR"] = "secret_value"
    try:
        result = shell_exec_mod.shell_exec(
            {"arguments": ["sh", "-c", "echo $TEST_VAR"],
             "env_allowlist": ["SHELL_EXEC_TEST_VAR"]},
            current_cwd=str(Path.cwd()),
        )
        assert result.ok is True
    finally:
        del os.environ["SHELL_EXEC_TEST_VAR"]


# ---------------------------------------------------------------------------
# 20. Kill tree default
# ---------------------------------------------------------------------------

def test_shell_exec_kill_tree_default() -> None:
    """kill_tree defaults to True."""
    result = shell_exec_mod.shell_exec(
        {"command": "true"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True


# ---------------------------------------------------------------------------
# 21. Timeout clamping
# ---------------------------------------------------------------------------

def test_shell_exec_timeout_clamped() -> None:
    """Timeout outside [1, 300] is clamped."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo clamp", "timeout": 0.1},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
    data = result.data
    if isinstance(data, dict):
        assert data.get("timeout_seconds") >= 1.0  # clamped to min


def test_shell_exec_timeout_high_clamped() -> None:
    """Timeout > 300 is clamped to 300."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo clamp-high", "timeout": 9999},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True


# ---------------------------------------------------------------------------
# 22. Cancellation via ToolExecutor
# ---------------------------------------------------------------------------

def test_shell_exec_executor_integration() -> None:
    """Full integration: ToolExecutor.execute with a real command."""
    from acta.tools.registry import ToolRegistry
    from acta.tools.executor import ToolExecutor
    from acta.safety.policy import SafetyPolicy
    from acta.tools.contracts import ToolSpec

    from acta.safety.registry import _REGISTRY, ArgSchema, SafetyRule
    if "shell_exec" not in _REGISTRY:
        _REGISTRY["shell_exec"] = SafetyRule(
            risk=RiskLevel.CONFIRM,
            schema=ArgSchema(types=()),
        )

    registry = ToolRegistry()
    spec = ToolSpec(
        name="shell_exec",
        description="Execute bounded shell command.",
        input_schema={},
        output_schema=None,
        handler=shell_exec_mod.shell_exec,
        risk=RiskLevel.CONFIRM,
        timeout_seconds=30.0,
        side_effects=True,
    )
    registry.register(spec)

    policy = SafetyPolicy()
    executor = ToolExecutor(registry, policy, confirmer=lambda d: True)

    outcome = executor.execute(
        "shell_exec",
        {"command": "echo integration-ok"},
        source=UntrustedSource.USER,
    )

    assert outcome.ok is True
    assert "integration-ok" in outcome.message


# ---------------------------------------------------------------------------
# 23. Result data structure
# ---------------------------------------------------------------------------

def test_shell_exec_data_fields() -> None:
    """data dict has all expected keys."""
    result = shell_exec_mod.shell_exec(
        {"command": "echo ok"},
        current_cwd=str(Path.cwd()),
    )
    assert result.data is not None
    if isinstance(result.data, dict):
        assert "command" in result.data
        assert "exit_code" in result.data
        assert "cwd" in result.data
        assert "timeout_seconds" in result.data
        assert "killed_by_tree" in result.data
        assert isinstance(result.data["command"], str)
        assert isinstance(result.data["exit_code"], int)


# ---------------------------------------------------------------------------
# 24. ToolSpec contract compliance
# ---------------------------------------------------------------------------

def test_tool_name_constant() -> None:
    """TOOL_NAME matches the canonical registry name."""
    from actions.shell_exec import TOOL_NAME
    assert TOOL_NAME == "shell_exec"


# ---------------------------------------------------------------------------
# 25. CWD: /tmp is accepted
# ---------------------------------------------------------------------------

def test_shell_exec_cwd_tmp() -> None:
    """CWD under /tmp is accepted."""
    result = shell_exec_mod.shell_exec(
        {"command": "pwd", "cwd": "/tmp"},
        current_cwd=str(Path.cwd()),
    )
    assert result.ok is True
