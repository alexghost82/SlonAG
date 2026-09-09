"""Production-path tests for the registered shell_exec handler."""

from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

from acta.safety.types import UntrustedSource
from acta.tools.builtin import build_builtin_registry
from acta.tools.executor import ToolExecutor
from acta.tools.legacy import LEGACY_HANDLERS
from acta.tools.legacy.adapters import shell_exec_handler


def test_registered_handler_is_hardened_argv_executor() -> None:
    handler = LEGACY_HANDLERS["shell_exec"]
    assert handler is shell_exec_handler
    source = inspect.getsource(handler)
    assert "asyncio.create_subprocess_shell" not in source
    assert "create_subprocess_shell(" not in source
    from actions import shell_exec as hardened

    assert "shell_exec" in inspect.getsource(handler)
    assert hardened.shell_exec is not handler


def test_production_handler_accepts_legacy_cmd() -> None:
    result = LEGACY_HANDLERS["shell_exec"]({"cmd": "echo production-cmd"})
    assert result.ok is True
    assert "production-cmd" in (result.message or "")


def test_production_handler_via_tool_executor() -> None:
    registry = build_builtin_registry()
    spec = registry.get("shell_exec")
    assert spec.handler is LEGACY_HANDLERS["shell_exec"]
    from acta.tools.contracts import CancellationClass

    assert spec.cancellation_class is CancellationClass.KILLABLE

    class AllowAll:
        def validate_args(self, name: str, args: object) -> dict[str, object]:
            return dict(args) if isinstance(args, dict) else {}

        def authorize(self, name: str, args: object, **_kwargs: object) -> object:
            from acta.safety import SafetyDecision
            from acta.safety.types import DecisionKind, RiskLevel

            return SafetyDecision(
                kind=DecisionKind.ALLOW,
                tool_name=name,
                risk=RiskLevel.READ,
                source=UntrustedSource.USER,
                intent="test",
                args=dict(args) if isinstance(args, dict) else {},
            )

    executor = ToolExecutor(registry, AllowAll())  # type: ignore[arg-type]
    result = executor.execute(
        "shell_exec",
        {"command": "echo via-executor"},
        source=UntrustedSource.USER,
    )
    assert result.ok is True


@pytest.mark.asyncio
async def test_production_handler_async_path_does_not_block_loop() -> None:
    registry = build_builtin_registry()

    class AllowAll:
        def validate_args(self, name: str, args: object) -> dict[str, object]:
            return dict(args) if isinstance(args, dict) else {}

        def authorize(self, name: str, args: object, **_kwargs: object) -> object:
            from acta.safety import SafetyDecision
            from acta.safety.types import DecisionKind, RiskLevel

            return SafetyDecision(
                kind=DecisionKind.ALLOW,
                tool_name=name,
                risk=RiskLevel.READ,
                source=UntrustedSource.USER,
                intent="test",
                args=dict(args) if isinstance(args, dict) else {},
            )

    executor = ToolExecutor(registry, AllowAll())  # type: ignore[arg-type]
    result = await executor.execute_async(
        "shell_exec",
        {"command": "echo async-loop"},
        source=UntrustedSource.USER,
    )
    assert result.ok is True
    assert result.retryable is False


def test_cancel_event_before_exec() -> None:
    registry = build_builtin_registry()

    class AllowAll:
        def validate_args(self, name: str, args: object) -> dict[str, object]:
            return dict(args) if isinstance(args, dict) else {}

        def authorize(self, name: str, args: object, **_kwargs: object) -> object:
            from acta.safety import SafetyDecision
            from acta.safety.types import DecisionKind, RiskLevel

            return SafetyDecision(
                kind=DecisionKind.ALLOW,
                tool_name=name,
                risk=RiskLevel.READ,
                source=UntrustedSource.USER,
                intent="test",
                args=dict(args) if isinstance(args, dict) else {},
            )

    cancel = threading.Event()
    cancel.set()
    result = ToolExecutor(registry, AllowAll()).execute(  # type: ignore[arg-type]
        "shell_exec",
        {"command": "echo should-cancel"},
        source=UntrustedSource.USER,
        cancel_event=cancel,
    )
    assert result.code == "cancelled"
    assert Path.cwd().exists()
