"""Wave 14 compatibility coverage for AgentExecutor canonical dispatch."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from agent.executor import AgentExecutor, ToolDeniedError
from acta.safety import DecisionKind, RiskLevel, SafetyDecision, UntrustedSource
from acta.tools import ToolExecutor, ToolRegistry, ToolResult, ToolSpec


class RecordingExecutor:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object], UntrustedSource, str]] = []

    def execute(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        source: UntrustedSource,
        intent: str = "",
    ) -> ToolResult:
        self.calls.append((name, dict(arguments), source, intent))
        return self.result


def test_plan_step_reaches_injected_canonical_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.error_handler as error_handler
    import agent.planner as planner

    injected = RecordingExecutor(
        ToolResult(ok=True, code="ok", message="canonical result")
    )
    executor = AgentExecutor(tool_executor=injected)  # type: ignore[arg-type]
    monkeypatch.setattr(
        planner,
        "create_plan",
        lambda _goal: {
            "steps": [
                {
                    "step": 1,
                    "tool": "web_search",
                    "description": "Search",
                    "parameters": {"query": "offline"},
                }
            ]
        },
    )
    monkeypatch.setattr(
        error_handler,
        "analyze_error",
        lambda *_args, **_kwargs: pytest.fail("successful result must not recover"),
    )
    monkeypatch.setattr(executor, "_summarize", lambda *_args: "finished")

    assert executor.execute("research locally") == "finished"
    assert injected.calls == [
        (
            "web_search",
            {"query": "offline"},
            UntrustedSource.USER,
            "research locally",
        )
    ]


class DenyPolicy:
    def validate_args(self, _name: str, args: object) -> dict[str, object]:
        assert isinstance(args, Mapping)
        return dict(args)

    def authorize(
        self, name: str, args: object, *, source: UntrustedSource, intent: str = ""
    ) -> SafetyDecision:
        assert isinstance(args, Mapping)
        return SafetyDecision(
            kind=DecisionKind.DENY,
            tool_name=name,
            risk=RiskLevel.READ,
            source=source,
            intent=intent,
            args=dict(args),
            reason="denied",
        )


class AllowPolicy(DenyPolicy):
    def authorize(
        self, name: str, args: object, *, source: UntrustedSource, intent: str = ""
    ) -> SafetyDecision:
        decision = super().authorize(name, args, source=source, intent=intent)
        return SafetyDecision(
            kind=DecisionKind.ALLOW,
            tool_name=decision.tool_name,
            risk=decision.risk,
            source=decision.source,
            intent=decision.intent,
            args=decision.args,
        )


def test_denied_canonical_result_has_no_side_effect() -> None:
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="probe",
            description="probe",
            input_schema={"type": "object"},
            output_schema=None,
            handler=lambda args: calls.append(dict(args)),
            risk=RiskLevel.READ,
        )
    )
    canonical = ToolExecutor(registry, DenyPolicy())  # type: ignore[arg-type]
    executor = AgentExecutor(registry=registry, tool_executor=canonical)

    with pytest.raises(ToolDeniedError):
        executor._call_tool("probe", {"value": 1}, None, intent="test")

    assert calls == []


def test_failed_tool_result_is_not_reported_as_success() -> None:
    injected = RecordingExecutor(
        ToolResult(ok=False, code="handler_error", message="Tool handler failed.")
    )
    executor = AgentExecutor(tool_executor=injected)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Tool handler failed"):
        executor._call_tool("web_search", {"query": "x"}, None)


def test_legacy_speak_is_bound_as_context_not_as_model_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spoken: list[str] = []

    def fake_action(*, parameters: dict, player: object, speak: object) -> str:
        assert parameters == {"game": "demo"}
        assert player is None
        assert callable(speak)
        speak("progress")  # type: ignore[operator]
        return "updated"

    monkeypatch.setitem(
        sys.modules,
        "actions.game_updater",
        SimpleNamespace(game_updater=fake_action),
    )
    executor = AgentExecutor(policy=AllowPolicy())  # type: ignore[arg-type]

    result = executor._call_tool(
        "game_updater", {"game": "demo"}, spoken.append, intent="update"
    )

    assert result == "updated"
    assert spoken == ["progress"]
