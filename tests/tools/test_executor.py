from __future__ import annotations

import threading
import time
from collections.abc import Mapping

import pytest

from mark.safety import (
    DecisionKind,
    RiskLevel,
    SafetyDecision,
    SafetyPolicy,
    UntrustedSource,
)
from mark.tools import SideEffectClass, ToolExecutor, ToolRegistry, ToolResult, ToolSpec


class RecordingPolicy:
    def __init__(self, kind: DecisionKind = DecisionKind.ALLOW) -> None:
        self.kind = kind
        self.events: list[str] = []

    def validate_args(self, name: str, args: object) -> dict[str, object]:
        self.events.append("validate")
        if not isinstance(args, Mapping) or "value" not in args:
            raise ValueError("secret validation detail")
        return dict(args)

    def authorize(
        self,
        name: str,
        args: object,
        *,
        source: UntrustedSource,
        intent: str,
    ) -> SafetyDecision:
        self.events.append("authorize")
        return SafetyDecision(
            kind=self.kind,
            tool_name=name,
            risk=(
                RiskLevel.CONFIRM
                if self.kind is DecisionKind.CONFIRM
                else RiskLevel.READ
            ),
            source=source,
            intent=intent,
            args=dict(args),
        )


def build_executor(
    handler: object,
    policy: RecordingPolicy,
    *,
    confirmer: object = None,
    timeout: float = 1.0,
    idempotent: bool = False,
) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "web_search",
            "Search",
            {},
            None,
            handler,
            RiskLevel.READ,
            timeout_seconds=timeout,
            idempotent=idempotent,
        )
    )
    return ToolExecutor(registry, policy, confirmer=confirmer)  # type: ignore[arg-type]


def test_execution_order_and_native_result() -> None:
    policy = RecordingPolicy()

    def handler(args: Mapping[str, object]) -> ToolResult:
        policy.events.append("handler")
        return ToolResult(ok=True, code="searched", data=dict(args))

    result = build_executor(handler, policy).execute(
        "web_search", {"value": "x"}, source=UntrustedSource.USER
    )

    assert result.ok and result.code == "searched"
    assert result.data == {"value": "x"}
    assert result.started_at is not None and result.finished_at is not None
    assert result.started_at <= result.finished_at
    assert policy.events == ["validate", "authorize", "handler"]


@pytest.mark.parametrize("kind", [DecisionKind.DENY, DecisionKind.CONFIRM])
def test_denied_or_unconfirmed_never_calls_handler(kind: DecisionKind) -> None:
    called = False
    policy = RecordingPolicy(kind)

    def handler(args: Mapping[str, object]) -> None:
        nonlocal called
        called = True

    result = build_executor(handler, policy).execute(
        "web_search", {"value": "x"}, source=UntrustedSource.USER
    )

    assert not result.ok
    assert not called


def test_confirmation_precedes_handler() -> None:
    policy = RecordingPolicy(DecisionKind.CONFIRM)

    def confirmer(decision: SafetyDecision) -> bool:
        policy.events.append("confirm")
        return True

    def handler(args: Mapping[str, object]) -> str:
        policy.events.append("handler")
        return "done"

    result = build_executor(handler, policy, confirmer=confirmer).execute(
        "web_search", {"value": "x"}, source=UntrustedSource.USER
    )

    assert result.ok and result.message == "done"
    assert policy.events == ["validate", "authorize", "confirm", "handler"]


def test_canonical_tool_call_id_reaches_confirmation_for_single_and_batch() -> None:
    policy = RecordingPolicy(DecisionKind.CONFIRM)
    correlated: list[str | None] = []
    executor = build_executor(
        lambda arguments: arguments,
        policy,
        confirmer=lambda decision: correlated.append(decision.tool_call_id) or True,
    )

    first = executor.execute(
        "web_search", {"value": "single"}, source=UntrustedSource.USER,
        tool_call_id="provider-single",
    )
    batch = executor.execute_many(
        (("provider-batch", "web_search", {"value": "batch"}),),
        source=UntrustedSource.USER,
    )

    assert first.ok and batch[0].ok
    assert correlated == ["provider-single", "provider-batch"]


def test_model_override_fields_do_not_skip_policy_confirmation() -> None:
    policy = RecordingPolicy(DecisionKind.CONFIRM)
    called = False

    def handler(args: Mapping[str, object]) -> None:
        nonlocal called
        called = True

    result = build_executor(handler, policy).execute(
        "web_search",
        {"value": "x", "confirmed": True, "risk": "READ", "skip_confirm": True},
        source=UntrustedSource.USER,
    )

    assert result.code == "confirmation_required"
    assert not called


def test_real_policy_rejects_untrusted_dangerous_call_despite_overrides() -> None:
    called = False

    def handler(args: Mapping[str, object]) -> None:
        nonlocal called
        called = True

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "file_controller",
            "Files",
            {},
            None,
            handler,
            RiskLevel.CONFIRM,
        )
    )
    result = ToolExecutor(registry, SafetyPolicy()).execute(
        "file_controller",
        {
            "action": "delete",
            "path": "irrelevant",
            "confirmed": True,
            "risk": "READ",
            "skip_confirm": True,
        },
        source=UntrustedSource.WEB,
    )

    assert result.code == "denied"
    assert not called


def test_unknown_and_invalid_arguments_are_normalized() -> None:
    policy = RecordingPolicy()
    executor = build_executor(lambda args: None, policy)

    unknown = executor.execute("missing", {}, source=UntrustedSource.USER)
    invalid = executor.execute("web_search", {}, source=UntrustedSource.USER)

    assert unknown.code == "unknown_tool" and "missing" not in unknown.message
    assert invalid.code == "invalid_args" and "secret" not in invalid.message
    assert policy.events == ["validate"]


def test_handler_exception_is_normalized_without_details() -> None:
    policy = RecordingPolicy()

    def handler(args: Mapping[str, object]) -> None:
        raise RuntimeError("api-key=do-not-leak")

    result = build_executor(handler, policy).execute(
        "web_search", {"value": "x"}, source=UntrustedSource.USER
    )

    assert result.code == "handler_error"
    assert "api-key" not in result.message
    assert result.data is None


def test_timeout_is_bounded_and_handler_is_not_retried() -> None:
    release = threading.Event()
    calls = 0

    def handler(args: Mapping[str, object]) -> None:
        nonlocal calls
        calls += 1
        release.wait(1.0)

    try:
        result = build_executor(
            handler, RecordingPolicy(), timeout=0.01, idempotent=True
        ).execute("web_search", {"value": "x"}, source=UntrustedSource.USER)
        assert result.code == "timeout" and result.retryable
        assert calls == 1
        assert result.warnings
    finally:
        release.set()


def test_execute_many_parallel_safe_preserves_input_order() -> None:
    registry = ToolRegistry()
    barrier = threading.Barrier(2)

    def handler(arguments):
        barrier.wait(timeout=1)
        return {"value": arguments["value"]}

    for name in ("read_a", "read_b"):
        registry.register(
            ToolSpec(
                name=name,
                description=name,
                input_schema={"type": "object"},
                output_schema=None,
                handler=handler,
                risk=RiskLevel.READ,
                read_only=True,
                idempotent=True,
                side_effects=False,
                parallel_safe=True,
            )
        )
    executor = ToolExecutor(registry, RecordingPolicy())  # type: ignore[arg-type]

    results = executor.execute_many(
        (("read_a", {"value": 1}), ("read_b", {"value": 2})),
        source=UntrustedSource.USER,
    )

    assert [result.data for result in results] == [{"value": 1}, {"value": 2}]


def test_execute_many_side_effects_are_sequential() -> None:
    registry = ToolRegistry()
    active = 0
    max_active = 0

    def handler(arguments):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        time.sleep(0.01)
        active -= 1
        return arguments

    registry.register(
        ToolSpec(
            name="write",
            description="write",
            input_schema={"type": "object"},
            output_schema=None,
            handler=handler,
            risk=RiskLevel.CONFIRM,
        )
    )
    executor = ToolExecutor(registry, RecordingPolicy())  # type: ignore[arg-type]
    executor.execute_many(
        (("write", {"value": 1}), ("write", {"value": 2})),
        source=UntrustedSource.USER,
    )

    assert max_active == 1


def test_tool_spec_rejects_parallel_side_effect_metadata() -> None:
    with pytest.raises(ValueError, match="parallel_safe"):
        ToolSpec(
            name="unsafe", description="unsafe", input_schema={"type": "object"},
            output_schema=None, handler=lambda _arguments: None,
            risk=RiskLevel.CONFIRM, parallel_safe=True,
        )


def test_tool_spec_rejects_inconsistent_side_effect_class() -> None:
    with pytest.raises(ValueError, match="disagree"):
        ToolSpec(
            name="inconsistent", description="inconsistent",
            input_schema={"type": "object"}, output_schema=None,
            handler=lambda _arguments: None, risk=RiskLevel.READ,
            side_effects=False, side_effect_class=SideEffectClass.IRREVERSIBLE,
        )


def test_duplicate_parallel_safe_calls_are_serialized() -> None:
    registry = ToolRegistry()
    active = 0
    max_active = 0

    def handler(arguments):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        time.sleep(0.01)
        active -= 1
        return arguments

    registry.register(ToolSpec(
        name="read", description="read", input_schema={"type": "object"},
        output_schema=None, handler=handler, risk=RiskLevel.READ,
        read_only=True, idempotent=True, side_effects=False, parallel_safe=True,
    ))
    executor = ToolExecutor(registry, RecordingPolicy())  # type: ignore[arg-type]
    executor.execute_many(
        (("read", {"value": 1}), ("read", {"value": 1})),
        source=UntrustedSource.USER,
    )
    assert max_active == 1


def test_approval_and_handler_timing_are_reported_separately() -> None:
    executor = build_executor(
        lambda arguments: arguments,
        RecordingPolicy(DecisionKind.CONFIRM),
        confirmer=lambda _decision: True,
    )
    result = executor.execute(
        "web_search", {"value": "x"}, source=UntrustedSource.USER
    )
    assert result.approval_started_at is not None
    assert result.approval_finished_at is not None
    assert result.handler_started_at is not None
    assert result.approval_started_at <= result.approval_finished_at
    assert result.approval_finished_at <= result.handler_started_at


@pytest.mark.parametrize(
    ("legacy", "message", "data"),
    [(None, "", None), ("done", "done", None), ({"x": 1}, "", {"x": 1})],
)
def test_minimal_legacy_normalization(
    legacy: object, message: str, data: object
) -> None:
    result = build_executor(lambda args: legacy, RecordingPolicy()).execute(
        "web_search", {"value": "x"}, source=UntrustedSource.USER
    )
    assert result.ok and result.message == message and result.data == data
