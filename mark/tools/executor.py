"""Canonical, safety-gated execution pipeline for registered tools."""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import replace
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor

from mark.safety import DecisionKind, SafetyDecision, SafetyPolicy, UntrustedSource
from mark.tools.contracts import ToolResult
from mark.tools.registry import ToolRegistry


_CONFIRMATION_KINDS = frozenset(
    {DecisionKind.CONFIRM, DecisionKind.EXACT_CONFIRM, DecisionKind.BIOMETRIC}
)


class ToolExecutor:
    """Validate, authorize, approve and execute canonical tool handlers."""

    def __init__(
        self,
        registry: ToolRegistry,
        safety_policy: SafetyPolicy,
        confirmer: Callable[..., bool] | None = None,
    ) -> None:
        self._registry = registry
        self._safety_policy = safety_policy
        self._confirmer = confirmer

    @property
    def registry(self) -> ToolRegistry:
        """Canonical definitions used by this executor."""
        return self._registry

    def execute(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        source: UntrustedSource,
        intent: str = "",
        cancel_event: threading.Event | None = None,
    ) -> ToolResult:
        """Execute one tool call and return a non-throwing structured outcome."""
        started_at = time.monotonic()
        approval_started_at: float | None = None
        approval_finished_at: float | None = None

        if cancel_event is not None and cancel_event.is_set():
            return self._error("cancelled", "Tool execution was cancelled.", started_at)

        try:
            spec = self._registry.get(name)
        except Exception:
            return self._error("unknown_tool", "Unknown tool.", started_at)

        try:
            checked = self._safety_policy.validate_args(name, arguments)
        except Exception:
            return self._error(
                "invalid_args", "Tool arguments failed validation.", started_at
            )

        try:
            decision = self._safety_policy.authorize(
                name, checked, source=source, intent=intent
            )
        except Exception:
            return self._error(
                "policy_error", "Safety policy could not authorize the tool.", started_at
            )

        if decision.kind is DecisionKind.DENY:
            return self._error("denied", "Tool is refused by policy.", started_at)

        if decision.kind in _CONFIRMATION_KINDS:
            if self._confirmer is None:
                return self._error(
                    "confirmation_required", "Confirmation is required.", started_at
                )
            try:
                approval_started_at = time.monotonic()
                confirmed = bool(self._confirmer(decision))
                approval_finished_at = time.monotonic()
            except Exception:
                approval_finished_at = time.monotonic()
                return replace(
                    self._error(
                        "confirmation_error",
                        "Confirmation could not be obtained.",
                        started_at,
                    ),
                    approval_started_at=approval_started_at,
                    approval_finished_at=approval_finished_at,
                )
            if not confirmed:
                return replace(
                    self._error(
                        "confirmation_declined", "Confirmation was declined.", started_at
                    ),
                    approval_started_at=approval_started_at,
                    approval_finished_at=approval_finished_at,
                )

        if cancel_event is not None and cancel_event.is_set():
            return self._error("cancelled", "Tool execution was cancelled.", started_at)

        handler_started_at = time.monotonic()
        outcome = self._invoke(spec.handler, checked, spec.timeout_seconds)
        if outcome is _TIMED_OUT:
            warning = (
                "The handler did not finish before the deadline; an already running "
                "legacy operation may continue."
            )
            return ToolResult(
                ok=False,
                code="timeout",
                message="Tool execution timed out.",
                warnings=(warning,),
                started_at=started_at,
                finished_at=time.monotonic(),
                approval_started_at=approval_started_at,
                approval_finished_at=approval_finished_at,
                handler_started_at=handler_started_at,
                retryable=spec.idempotent,
            )

        if isinstance(outcome, _HandlerFailure):
            return ToolResult(
                ok=False,
                code="handler_error",
                message="Tool handler failed.",
                started_at=started_at,
                finished_at=time.monotonic(),
                approval_started_at=approval_started_at,
                approval_finished_at=approval_finished_at,
                handler_started_at=handler_started_at,
                retryable=outcome.retryable and spec.idempotent,
            )

        return replace(
            self._normalize(outcome, started_at),
            approval_started_at=approval_started_at,
            approval_finished_at=approval_finished_at,
            handler_started_at=handler_started_at,
        )

    def execute_many(
        self,
        calls: Sequence[tuple[str, Mapping[str, object]]],
        *,
        source: UntrustedSource,
        intent: str = "",
        cancel_event: threading.Event | None = None,
    ) -> tuple[ToolResult, ...]:
        """Execute a batch in input order, parallelizing only explicitly safe tools."""
        if not calls:
            return ()
        specs = []
        for name, _arguments in calls:
            try:
                specs.append(self._registry.get(name))
            except Exception:
                specs.append(None)
        safely_parallel = all(
            spec is not None
            and spec.parallel_safe
            and spec.read_only
            and spec.idempotent
            and not spec.side_effects
            for spec in specs
        )
        # Duplicate calls are conservatively serialized: they may contend for
        # the same remote or local resource even when the operation is a read.
        identities = [
            (name, repr(sorted(arguments.items()))) for name, arguments in calls
        ]
        independent = len(set(identities)) == len(identities)
        if not safely_parallel or not independent:
            return tuple(
                self.execute(
                    name, arguments, source=source, intent=intent,
                    cancel_event=cancel_event,
                )
                for name, arguments in calls
            )
        with ThreadPoolExecutor(
            max_workers=min(len(calls), 8), thread_name_prefix="slon-tool-batch"
        ) as pool:
            futures = [
                pool.submit(
                    self.execute, name, arguments, source=source, intent=intent,
                    cancel_event=cancel_event,
                )
                for name, arguments in calls
            ]
            return tuple(future.result() for future in futures)

    @staticmethod
    def _invoke(
        handler: Callable[..., object],
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> object:
        results: queue.Queue[object] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                results.put(handler(arguments))
            except Exception as exc:
                results.put(
                    _HandlerFailure(
                        retryable=isinstance(exc, (ConnectionError, TimeoutError))
                    )
                )

        worker = threading.Thread(target=run, name="slon-tool-handler", daemon=True)
        worker.start()
        try:
            return results.get(timeout=timeout_seconds)
        except queue.Empty:
            return _TIMED_OUT

    @staticmethod
    def _normalize(value: object, started_at: float) -> ToolResult:
        finished_at = time.monotonic()
        if isinstance(value, ToolResult):
            return ToolResult(
                ok=value.ok,
                code=value.code,
                message=value.message,
                data=value.data,
                artifacts=value.artifacts,
                warnings=value.warnings,
                started_at=value.started_at if value.started_at is not None else started_at,
                finished_at=(
                    value.finished_at if value.finished_at is not None else finished_at
                ),
                retryable=value.retryable,
            )
        if value is None:
            return ToolResult(
                ok=True,
                code="ok",
                started_at=started_at,
                finished_at=finished_at,
            )
        if isinstance(value, str):
            return ToolResult(
                ok=True,
                code="ok",
                message=value,
                started_at=started_at,
                finished_at=finished_at,
            )
        if isinstance(value, dict):
            return ToolResult(
                ok=True,
                code="ok",
                data=value,
                started_at=started_at,
                finished_at=finished_at,
            )
        return ToolResult(
            ok=False,
            code="invalid_result",
            message="Tool handler returned an unsupported result.",
            started_at=started_at,
            finished_at=finished_at,
        )

    @staticmethod
    def _error(code: str, message: str, started_at: float) -> ToolResult:
        return ToolResult(
            ok=False,
            code=code,
            message=message,
            started_at=started_at,
            finished_at=time.monotonic(),
        )


class _HandlerFailure:
    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable


_TIMED_OUT = object()


__all__ = ["ToolExecutor"]
