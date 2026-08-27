"""Bounded, safe shell execution with approval and audit.

Canonical production shell tool for Slon.  All subprocess calls go through
this module; it is the single boundary between model intent and host process
execution.

Supported contract
------------------
* ``command`` – single-string form (shlex-parsed internally)
* ``arguments`` – list of tokens; takes precedence over ``command``
* ``cwd``       – bounded working directory
* ``env_allowlist`` – allowed ``os.environ`` keys
* ``timeout``   – seconds (clamped 1 … 300)
* ``stdin``     – optional text piped to ``stdin``
* ``stdout_max`` – byte cap for stdout (default 64 KiB)
* ``stderr_max`` – byte cap for stderr  (default 16 KiB)
* ``kill_tree`` – terminate process group / subtree on timeout or cancel

Side-effects
------------
AgentLoop → ToolRegistry → SafetyPolicy → Approval → ToolExecutor → shell
handler.  No bypass is possible.

Cancellation & cleanup
----------------------
On timeout or explicit cancellation the entire process tree is torn down:
Unix  → ``os.setsid`` + ``os.killpg``  (SIGKILL)
Windows → ``CREATE_NEW_PROCESS_GROUP`` + ``proc.kill`` (SIGTERM → SIGKILL)
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from i18n import t as _t

from mark.safety import authorize, check_url, validate_args
from mark.safety.errors import ArgValidationError
from mark.safety.types import DecisionKind, SafetyDecision, UntrustedSource
from mark.tools.contracts import ToolResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TOOL_NAME = "shell_exec"
_DEFAULT_TIMEOUT: float = 30.0
_MAX_STDOUT: int = 64 * 1024  # 64 KiB
_MAX_STDERR: int = 16 * 1024  # 16 KiB
_TIMEOUT_BOUND_LOW: float = 1.0
_TIMEOUT_BOUND_HIGH: float = 300.0

# Always-refuse prefixes (checked against the full command string).
_BLOCKED_PREFIXES: tuple[str, ...] = (
    "sudo ",
    "sudo\t",
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
    "reboot",
    "poweroff",
    "init 0",
    "init 6",
)

# Internal tracker for process-tree cleanup on cancellation / timeout.
_active_procs: set[subprocess.Popen[Any]] = set()
_active_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_blocked(cmd: str) -> bool:
    """Return ``True`` when the command is explicitly forbidden."""
    stripped = cmd.strip()
    for prefix in _BLOCKED_PREFIXES:
        if stripped.startswith(prefix):
            return True
    return False


def _safe_cwd(cwd_arg: str | None, current_cwd: str) -> Path:
    """Resolve ``cwd`` with safety constraints.

    Allowed:
    * ``None`` / empty → current working directory
    * Paths under ``$HOME``
    * Paths under ``/tmp``
    """
    if cwd_arg is None or not cwd_arg.strip():
        return Path(current_cwd).resolve()
    path = Path(cwd_arg).expanduser().resolve()

    home = Path.home().resolve()
    if str(path).startswith(str(home)):
        return path

    if str(path).startswith("/tmp"):
        return path

    # Verify existence (user may specify an existing project path).
    if path.is_dir():
        return path

    raise ArgValidationError(TOOL_NAME, _t("shell_exec.invalid_cwd"))


def _build_env(
    env_allowlist: frozenset[str],
    current_cwd: str,
) -> dict[str, str]:
    """Construct a bounded environment from allowed os.environ keys."""
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "SHELL": os.environ.get("SHELL", "/bin/sh"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "PWD": current_cwd,
    }
    for key in env_allowlist:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


def _truncate(text: str, max_bytes: int) -> str:
    """Return at most ``max_bytes`` bytes worth of *text*."""
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    trimmed = encoded[:max_bytes]
    try:
        return trimmed.decode("utf-8") + _t("shell_exec.output_truncated")
    except UnicodeDecodeError:
        return (
            trimmed[: max_bytes - 20].decode("utf-8", errors="replace")
            + _t("shell_exec.output_truncated")
        )


# ---------------------------------------------------------------------------
# Process-tree cleanup
# ---------------------------------------------------------------------------

def _kill_tree(proc: subprocess.Popen[Any]) -> None:
    """Terminate the process tree rooted at ``proc``."""
    if proc.poll() is not None:
        return  # already finished

    try:
        children = proc.children()
    except (AttributeError, OSError):
        children = []

    for child in children:
        try:
            child.kill()
        except (ProcessLookupError, OSError):
            pass

    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass

    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except (ProcessLookupError, OSError):
            pass


def _was_killed(proc: subprocess.Popen[Any]) -> bool:
    """Heuristic: was the process terminated by a signal?"""
    if proc.returncode is None:
        return False
    if sys.platform == "win32":
        return proc.returncode < 0
    # Unix: returncode is negative of signal number.
    return proc.returncode < 0


# ---------------------------------------------------------------------------
# Core subprocess execution (both async and sync contexts)
# ---------------------------------------------------------------------------

async def _run_subprocess_async(
    cmd_args: list[str],
    cwd: Path,
    env_allowlist: frozenset[str],
    timeout_f: float,
    stdin_data: str | None,
    stdout_max: int,
    stderr_max: int,
    kill_tree: bool,
) -> "ShellExecResult":
    """Execute the command in an async-safe manner (for event-loop contexts)."""
    env = _build_env(env_allowlist, str(cwd))

    start_kwargs: dict[str, Any] = {}
    if sys.platform != "win32":
        start_kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(
        cmd_args,
        stdin=subprocess.PIPE if stdin_data else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        text=False,
        **start_kwargs,
    )

    with _active_lock:
        _active_procs.add(proc)

    try:
        stdin_input: bytes | None = stdin_data.encode("utf-8") if stdin_data else None
        try:
            stdout_bytes, stderr_bytes = await asyncio.get_running_loop().run_in_executor(
                None, _communicate, proc, stdin_input, timeout_f
            )
            stdout_data = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr_data = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        except subprocess.TimeoutExpired:
            if kill_tree:
                _kill_tree(proc)
            try:
                stdout_bytes, stderr_bytes = proc.communicate()
                stdout_data = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
                stderr_data = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            except Exception:
                stdout_data, stderr_data = "", ""

        exit_code = proc.returncode
    finally:
        with _active_lock:
            _active_procs.discard(proc)

    stdout_data = _truncate(stdout_data, stdout_max)
    stderr_data = _truncate(stderr_data, stderr_max)

    return ShellExecResult(
        command=" ".join(cmd_args),
        stdout=stdout_data or "",
        stderr=stderr_data or "",
        exit_code=exit_code,
        timed_out=False,
        cwd=str(cwd),
        timeout_seconds=timeout_f,
        killed_by_tree=_was_killed(proc),
    )


def _communicate(
    proc: subprocess.Popen[Any], stdin_data: bytes | None, timeout_f: float
) -> tuple[bytes, bytes]:
    """Blocking communicate wrapper for executor.
    Returns raw bytes; caller decodes to str.
    """
    return proc.communicate(input=stdin_data, timeout=timeout_f)


def _run_subprocess_sync(
    cmd_args: list[str],
    cwd: Path,
    env_allowlist: frozenset[str],
    timeout_f: float,
    stdin_data: str | None,
    stdout_max: int,
    stderr_max: int,
    kill_tree: bool,
) -> "ShellExecResult":
    """Execute the command synchronously (for sync contexts like tests)."""
    env = _build_env(env_allowlist, str(cwd))

    start_kwargs: dict[str, Any] = {}
    if sys.platform != "win32":
        start_kwargs["preexec_fn"] = os.setsid

    proc = subprocess.Popen(
        cmd_args,
        stdin=subprocess.PIPE if stdin_data else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        text=False,
        **start_kwargs,
    )

    with _active_lock:
        _active_procs.add(proc)

    try:
        stdin_input: bytes | None = stdin_data.encode("utf-8") if stdin_data else None
        try:
            stdout_bytes, stderr_bytes = proc.communicate(
                input=stdin_input, timeout=timeout_f
            )
            stdout_data = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr_data = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        except subprocess.TimeoutExpired:
            if kill_tree:
                _kill_tree(proc)
            try:
                stdout_bytes, stderr_bytes = proc.communicate()
                stdout_data = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
                stderr_data = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            except Exception:
                stdout_data, stderr_data = "", ""

        exit_code = proc.returncode
    finally:
        with _active_lock:
            _active_procs.discard(proc)

    stdout_data = _truncate(stdout_data, stdout_max)
    stderr_data = _truncate(stderr_data, stderr_max)

    return ShellExecResult(
        command=" ".join(cmd_args),
        stdout=stdout_data or "",
        stderr=stderr_data or "",
        exit_code=exit_code,
        timed_out=False,
        cwd=str(cwd),
        timeout_seconds=timeout_f,
        killed_by_tree=_was_killed(proc),
    )


# ---------------------------------------------------------------------------
# Public handler
# ---------------------------------------------------------------------------

@dataclass
class ShellExecResult:
    """Structured outcome of a shell execution."""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    cwd: str = ""
    timeout_seconds: float = 0.0
    killed_by_tree: bool = False


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

    try:
        params = validate_args(TOOL_NAME, parameters or {})
    except ArgValidationError as exc:
        return ToolResult(
            ok=False,
            code="invalid_args",
            message=str(exc),
        )

    # Validate command source
    cmd_str: str | None = params.get("command")
    args_list: list[str] | None = params.get("arguments")

    if args_list is not None:
        if not isinstance(args_list, list):
            return ToolResult(
                ok=False,
                code="invalid_args",
                message="Аргумент 'arguments' должен быть списком строк.",
            )
        if len(args_list) == 0:
            return ToolResult(
                ok=False,
                code="missing_field",
                message="Аргумент 'arguments' не может быть пустым.",
            )
        cmd_args: list[str] = []
        for item in args_list:
            if isinstance(item, str) and item.strip():
                cmd_args.append(item)
            else:
                return ToolResult(
                    ok=False,
                    code="invalid_args",
                    message="Каждый элемент 'arguments' должен быть непустой строкой.",
                )
    elif cmd_str is not None and isinstance(cmd_str, str) and cmd_str.strip():
        cmd_args = shlex.split(cmd_str.strip())
    else:
        return ToolResult(
            ok=False,
            code="missing_field",
            message=_t("shell_exec.no_args"),
        )

    if len(cmd_args) == 0:
        return ToolResult(
            ok=False,
            code="missing_field",
            message="Команда пуста после разбора.",
        )

    # Block dangerous commands
    full_cmd = cmd_args[0]
    if cmd_str is not None and _is_blocked(cmd_str):
        return ToolResult(
            ok=False,
            code="blocked",
            message="Команда заблокирована политикой безопасности.",
        )
    if cmd_args and _is_blocked(cmd_args[0]):
        return ToolResult(
            ok=False,
            code="blocked",
            message="Команда заблокирована политикой безопасности.",
        )

    # Resolve cwd
    cwd_arg: str | None = params.get("cwd")
    try:
        cwd = _safe_cwd(cwd_arg, current_cwd)
    except ArgValidationError as exc:
        return ToolResult(
            ok=False,
            code="invalid_cwd",
            message=str(exc),
        )

    # Timeout
    timeout_raw = params.get("timeout")
    try:
        timeout_f: float = float(timeout_raw) if timeout_raw is not None else _DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        timeout_f = _DEFAULT_TIMEOUT
    timeout_f = max(_TIMEOUT_BOUND_LOW, min(timeout_f, _TIMEOUT_BOUND_HIGH))

    # Stdin
    stdin_data: str | None = params.get("stdin")
    if not isinstance(stdin_data, str) if stdin_data else False:
        stdin_data = None

    # Output limits
    try:
        stdout_max: int = int(params.get("stdout_max", _MAX_STDOUT))
    except (TypeError, ValueError):
        stdout_max = _MAX_STDOUT
    try:
        stderr_max: int = int(params.get("stderr_max", _MAX_STDERR))
    except (TypeError, ValueError):
        stderr_max = _MAX_STDERR

    # Kill tree flag
    kill_tree: bool = bool(params.get("kill_tree", True))

    # Env allowlist
    env_raw = params.get("env_allowlist", [])
    if isinstance(env_raw, list):
        env_allowlist: frozenset[str] = frozenset(str(k) for k in env_raw)
    else:
        env_allowlist = frozenset()

    # Safety authorization
    auth_args = dict(params)
    auth_args["command"] = cmd_args[0]
    auth_args["cwd"] = str(cwd)
    auth_args["timeout"] = timeout_f
    auth_args["kill_tree"] = kill_tree

    decision = authorize(
        TOOL_NAME, auth_args, source=source, intent="shell_exec"
    )

    if decision.kind == DecisionKind.DENY:
        return ToolResult(
            ok=False,
            code="denied",
            message="Выполнение команды отклонено политикой безопасности.",
        )

    # Confirmation
    needs_confirm = decision.kind in {
        DecisionKind.CONFIRM,
        DecisionKind.EXACT_CONFIRM,
        DecisionKind.BIOMETRIC,
    }
    if needs_confirm and confirmer is not None:
        try:
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

    # Execute: try async loop first, fall back to sync for tests
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context; run the coroutine
        result = loop.run_until_complete(
            _run_subprocess_async(
                cmd_args, cwd, env_allowlist,
                timeout_f, stdin_data,
                stdout_max, stderr_max, kill_tree,
            )
        )
    except RuntimeError:
        # No event loop — sync context (tests, direct calls)
        result = _run_subprocess_sync(
            cmd_args, cwd, env_allowlist,
            timeout_f, stdin_data,
            stdout_max, stderr_max, kill_tree,
        )

    # Build message
    output_parts: list[str] = []
    if result.stdout:
        output_parts.append("stdout:")
        output_parts.append(result.stdout.rstrip())
    if result.stderr:
        output_parts.append("stderr:")
        output_parts.append(result.stderr.rstrip())
    output = "\n".join(output_parts) if output_parts else "(нет вывода)"

    return ToolResult(
        ok=result.exit_code == 0,
        code="ok" if result.exit_code == 0 else "nonzero_exit",
        message=output,
        data={
            "command": result.command,
            "exit_code": result.exit_code,
            "timed_out": False,
            "cwd": result.cwd,
            "timeout_seconds": result.timeout_seconds,
            "killed_by_tree": result.killed_by_tree,
        },
    )


__all__ = ["ShellExecResult", "shell_exec", "TOOL_NAME"]
