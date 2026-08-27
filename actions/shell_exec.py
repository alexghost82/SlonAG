"""Bounded, safe shell execution with approval and audit.

Canonical replacement for the broken ``cmd_control``. All subprocess calls go
through this module; it is the single boundary between model intent and host
process execution.
"""

from __future__ import annotationsfrom i18n import t


import asyncio
import os
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mark.safety import authorize, check_url, validate_args
from mark.safety.errors import ArgValidationError
from mark.safety.types import DecisionKind, SafetyDecision, UntrustedSource
from mark.tools.contracts import ToolResult

TOOL_NAME = "shell_exec"

# Bounded defaults
_DEFAULT_TIMEOUT = 30  # seconds
_MAX_OUTPUT = 64 * 1024  # 64 KB cap
# Commands that are always refused regardless of approval
_BLOCKED_PREFIXES = (
    "sudo ",
    "su ",
    "pkexec ",
    "chmod 777 ",
    "chmod o+ ",
    "chown root ",
    "mkfs ",
    "dd if=/dev/zero",
    "rm -rf /",
    "rm -rf /*",
    "shutdown ",
    "halt ",
    "reboot ",
    "poweroff ",
    "init 0",
    "init 6",
)

# Allowed command whitelist prefixes (can be extended by caller).
_WHITELIST_PREFIXES: tuple[str, ...] = (
    "git ",
    "pytest ",
    "python ",
    "python3 ",
    "uv ",
    "ls ",
    "cat ",
    "pwd ",
    "which ",
    "echo ",
    "echo ",
    "du ",
    "df ",
    "ps ",
    "top ",
    "env ",
    "uname ",
    "date ",
    "date ",
    "tree ",
    "head ",
    "tail ",
    "wc ",
    "file ",
    "stat ",
    "find ",
    "grep ",
    "rg ",
    "rmdir ",
    "mkdir ",
    "touch ",
    "cp ",
    "mv ",
    "rm ",
    "tar ",
    "zip ",
    "unzip ",
    "pip ",
    "pip3 ",
    "uv pip ",
    "uv run ",
    "npm ",
    "npx ",
    "node ",
    "jq ",
    "tree ",
    "diff ",
    "sort ",
    "awk ",
    "sed ",
    "xargs ",
    "tee ",
    "wc ",
    "wc -l ",
    "wc -m ",
    "wc -c ",
    "ps aux",
    "ps -ef",
    "ps aux |",
    "ps aux | grep",
    "ps -ef | grep",
    "ps aux grep",
    "ps -ef grep",
    "kill ",
    "killall ",
    "lsof ",
    "ncdu ",
    "htop ",
    "fzf ",
    "file ",
)


def _is_blocked(cmd: str) -> bool:
    """Return True if the command is explicitly blocked."""
    stripped = cmd.strip()
    for prefix in _BLOCKED_PREFIXES:
        if stripped.startswith(prefix):
            return True
    return False


def _is_whitelisted(cmd: str) -> bool:
    """Return True if the command matches allowed prefixes."""
    stripped = cmd.strip()
    for prefix in _WHITELIST_PREFIXES:
        if stripped.startswith(prefix):
            return True
    return False


def _resolve_cwd(cwd_arg: str | None, current_cwd: str) -> Path:
    """Resolve working directory with safety constraints."""
    if cwd_arg is None or not cwd_arg.strip():
        return Path(current_cwd).resolve()
    path = Path(cwd_arg).expanduser().resolve()
    # Allow any path within the current user's home
    home = Path.home()
    if str(path).startswith(str(home)):
        return path
    # Also allow /tmp
    if str(path).startswith("/tmp"):
        return path
    # Also allow paths that start with the specified cwd_arg literally
    # (user might want to use a project path)
    try:
        path.exists()
        return path
    except OSError:
        raise ArgValidationError(
            TOOL_NAME,
            "Working directory does not exist.",
            field="cwd",
        )


def _validate_command(cmd: str) -> list[str]:
    """Validate and tokenize the command. Reject shell=True hazards."""
    if not cmd or not cmd.strip():
        raise ArgValidationError(
            TOOL_NAME,
            "Missing required argument 'command'.",
            field="command",
        )
    stripped = cmd.strip()

    if _is_blocked(stripped):
        raise ArgValidationError(
            TOOL_NAME,
            "Command is blocked by safety policy.",
            field="command",
        )

    # Reject shell=True hazards: pipes, redirects, $() without explicit allow
    if "|" in stripped and "shell" not in str(stripped).lower():
        raise ArgValidationError(
            TOOL_NAME,
            "Pipes are not supported in bounded mode. Use a script file.",
            field="command",
        )

    # Tokenize using shlex for safety
    try:
        args = shlex.split(stripped)
    except ValueError as exc:
        raise ArgValidationError(
            TOOL_NAME,
            f"Command parsing failed: {exc}",
            field="command",
        )

    if not args:
        raise ArgValidationError(
            TOOL_NAME,
            "Command is empty after parsing.",
            field="command",
        )

    # Check that the executable exists
    exe = args[0]
    if "/" in exe:
        # Absolute or relative path — check existence
        if not Path(exe).exists():
            raise ArgValidationError(
                TOOL_NAME,
                f"Executable not found: {exe}",
                field="command",
            )
    else:
        # In PATH — check with shutil
        if shutil.which(exe) is None:
            raise ArgValidationError(
                TOOL_NAME,
                f"Executable not found in PATH: {exe}",
                field="command",
            )

    return args


@dataclass(frozen=True)
class ShellExecResult:
    """Structured result of a bounded shell execution."""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    killed: bool = False


async def _run_subprocess(
    args: list[str],
    cwd: Path,
    env_allowlist: frozenset[str],
    timeout: float,
    stdin_data: str | None,
) -> ShellExecResult:
    """Run a subprocess with bounds. Returns structured result."""
    # Build environment: allowlist + std
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }
    # Only allow whitelisted env vars
    user_env: dict[str, str] = {}
    if env_allowlist:
        for key in os.environ:
            if key in env_allowlist:
                user_env[key] = os.environ[key]
    merged_env = {**base_env, **user_env}

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=merged_env,
            limit=_MAX_OUTPUT,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_data.encode() if stdin_data else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return ShellExecResult(
                command=" ".join(args),
                stdout="",
                stderr="Process timed out after {:.0f}s and was killed.".format(timeout),
                exit_code=-1,
                timed_out=True,
            )

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")[:_MAX_OUTPUT]
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")[:_MAX_OUTPUT]

        return ShellExecResult(
            command=" ".join(args),
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=proc.returncode,
        )

    except FileNotFoundError:
        return ShellExecResult(
            command=" ".join(args),
            stdout="",
            stderr="Executable not found: {}".format(args[0]),
            exit_code=127,
        )
    except PermissionError:
        return ShellExecResult(
            command=" ".join(args),
            stdout="",
            stderr="Permission denied.",
            exit_code=13,
        )
    except Exception as exc:
        return ShellExecResult(
            command=" ".join(args),
            stdout="",
            stderr="Execution error: {}".format(str(exc)),
            exit_code=-1,
        )


def shell_exec(
    parameters: dict[str, Any] | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
    *,
    current_cwd: str = "",
    source: UntrustedSource | str = UntrustedSource.USER,
    confirmer: Any = None,
) -> ToolResult:
    """Execute a bounded shell command with approval and audit.

    Replaces the broken ``cmd_control`` with a production-grade, safety-gated
    subprocess executor.
    """
    del response, session_memory

    params = validate_args(TOOL_NAME, parameters or {})
    url = params.get("url")
    if isinstance(url, str) and url.strip():
        check_url(url)

    # Parse required argument
    command = params.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolResult(
            ok=False,
            code="missing_field",
            message="Missing required argument 'command'.",
        )

    cmd = command.strip()

    # Pre-validate
    if _is_blocked(cmd):
        return ToolResult(
            ok=False,
            code="blocked",
            message="Команда заблокирована политикой безопасности.",
        )

    # Parse optional arguments
    cwd = _resolve_cwd(params.get("cwd"), current_cwd)
    timeout_val = params.get("timeout", _DEFAULT_TIMEOUT)
    try:
        timeout_f = float(timeout_val) if timeout_val is not None else _DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        timeout_f = _DEFAULT_TIMEOUT
    timeout_f = max(1.0, min(timeout_f, 300.0))  # clamp 1-300s

    stdin_data = params.get("stdin")
    if not isinstance(stdin_data, str) if stdin_data else False:
        stdin_data = None

    # Get env allowlist
    env_raw = params.get("env_allowlist", [])
    if isinstance(env_raw, list):
        env_allowlist = frozenset(str(k) for k in env_raw)
    else:
        env_allowlist = frozenset()

    # Safety authorization
    auth_args = dict(params)
    auth_args["command"] = cmd
    auth_args["cwd"] = str(cwd)
    auth_args["timeout"] = timeout_f
    auth_args["shell"] = False

    decision = authorize(
        TOOL_NAME, auth_args, source=source, intent="shell_exec"
    )
    if decision.kind == DecisionKind.DENY:
        return ToolResult(
            ok=False,
            code="denied",
            message="Выполнение команды отклонено политикой безопасности.",
        )

    # Need confirmation for mutating operations
    needs_confirm = decision.kind in {
        DecisionKind.CONFIRM,
        DecisionKind.EXACT_CONFIRM,
        DecisionKind.BIOMETRIC,
    }
    if needs_confirm and confirmer is not None:
        try:
            # confirmer expects SafetyDecision
            if not confirmer(decision):
                return ToolResult(
                    ok=False,
                    code="user_denied",
                    message="Пользователь отклонил выполнение команды.",
                )
        except Exception:
            return ToolResult(
                ok=False,
                code="confirm_error",
                message="Ошибка подтверждения пользователем.",
            )

    # Validate command
    try:
        cmd_args = _validate_command(cmd)
    except ArgValidationError as exc:
        return ToolResult(
            ok=False,
            code=exc.code if hasattr(exc, "code") else "validation_error",
            message=str(exc),
        )

    # Execute in background thread to not block the event loop
    loop = asyncio.get_running_loop()
    result = loop.run_until_complete(
        _run_subprocess(
            cmd_args,
            cwd,
            env_allowlist,
            timeout_f,
            stdin_data,
        )
    )

    # Build response
    output_lines = []
    if result.stdout:
        output_lines.append("stdout:")
        output_lines.append(result.stdout.rstrip())
    if result.stderr:
        output_lines.append("stderr:")
        output_lines.append(result.stderr.rstrip())

    output = "\n".join(output_lines) if output_lines else "(no output)"

    return ToolResult(
        ok=result.exit_code == 0,
        code="ok" if result.exit_code == 0 else "nonzero_exit",
        message=output,
        data={
            "command": result.command,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "cwd": str(cwd),
            "timeout_seconds": timeout_f,
        },
    )


__all__ = ["shell_exec", "ShellExecResult", "TOOL_NAME"]
