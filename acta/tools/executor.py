"""Canonical, safety-gated execution pipeline for registered tools."""

from __future__ import annotations

import asyncio
import inspect
import queue
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from acta.safety import DecisionKind, SafetyPolicy, UntrustedSource
from acta.tools.contracts import CancellationClass, ToolResult, ToolSpec
from acta.tools.registry import ToolRegistry

_CONFIRMATION_KINDS = frozenset(
    {DecisionKind.CONFIRM, DecisionKind.EXACT_CONFIRM, DecisionKind.BIOMETRIC}
)
_TRANSIENT_EXCEPTIONS = (ConnectionError, TimeoutError)
_TRANSIENT_CODES = frozenset({"timeout", "connection_error"})


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
        tool_call_id: str | None = None,
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
                confirmed = bool(
                    self._confirmer(replace(decision, tool_call_id=tool_call_id))
                )
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
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Execution was cancelled during approval.")
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
            warning = _timeout_warning(spec)
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
        calls: Sequence[
            tuple[str, Mapping[str, object]]
            | tuple[str, str, Mapping[str, object]]
        ],
        *,
        source: UntrustedSource,
        intent: str = "",
        cancel_event: threading.Event | None = None,
    ) -> tuple[ToolResult, ...]:
        """Execute a batch in input order, parallelizing only explicitly safe tools."""
        if not calls:
            return ()
        normalized_calls = tuple(self._normalize_call(call) for call in calls)
        if not self._calls_are_parallel_safe(normalized_calls):
            return tuple(
                self.execute(
                    name, arguments, source=source, intent=intent,
                    cancel_event=cancel_event, tool_call_id=tool_call_id,
                )
                for tool_call_id, name, arguments in normalized_calls
            )
        with ThreadPoolExecutor(
            max_workers=min(len(calls), 8), thread_name_prefix="slon-tool-batch"
        ) as pool:
            futures = [
                pool.submit(
                    self.execute, name, arguments, source=source, intent=intent,
                    cancel_event=cancel_event, tool_call_id=tool_call_id,
                )
                for tool_call_id, name, arguments in normalized_calls
            ]
            return tuple(future.result() for future in futures)

    @staticmethod
    def _normalize_call(
        call: tuple[str, Mapping[str, object]]
        | tuple[str, str, Mapping[str, object]],
    ) -> tuple[str | None, str, Mapping[str, object]]:
        """Accept legacy name/args pairs while preserving canonical call IDs."""
        if len(call) == 2:
            name, arguments = call
            return None, name, arguments
        tool_call_id, name, arguments = call
        return tool_call_id, name, arguments

    def _calls_are_parallel_safe(
        self,
        normalized_calls: Sequence[tuple[str | None, str, Mapping[str, object]]],
    ) -> bool:
        """Same gate for sync and async batches.

        Parallel only when every spec is parallel_safe, read_only, idempotent,
        side-effect free, and the calls are independent (no duplicate identity).
        """
        specs: list[ToolSpec | None] = []
        for _tool_call_id, name, _arguments in normalized_calls:
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
        identities = [
            (name, repr(sorted(arguments.items())))
            for _tool_call_id, name, arguments in normalized_calls
        ]
        independent = len(set(identities)) == len(identities)
        return bool(safely_parallel and independent)

    async def execute_async(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        source: UntrustedSource,
        intent: str = "",
        cancel_event: threading.Event | None = None,
        tool_call_id: str | None = None,
    ) -> ToolResult:
        """Async execute for use with async tool handlers (e.g., MCP tools)."""
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
                # Wrap confirmer in thread so asyncio.CancelledError can interrupt it
                confirmed = await asyncio.to_thread(
                    lambda: bool(
                        self._confirmer(replace(decision, tool_call_id=tool_call_id))
                    )
                )
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
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Execution was cancelled during approval.")
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
        try:
            outcome = await _invoke_handler_async(spec, arguments)
        except TimeoutError:
            return ToolResult(
                ok=False,
                code="timeout",
                message="Tool execution timed out.",
                warnings=(_timeout_warning(spec),),
                started_at=started_at,
                finished_at=time.monotonic(),
                approval_started_at=approval_started_at,
                approval_finished_at=approval_finished_at,
                handler_started_at=handler_started_at,
                retryable=spec.idempotent,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                code="handler_error",
                message="Tool handler failed.",
                started_at=started_at,
                finished_at=time.monotonic(),
                approval_started_at=approval_started_at,
                approval_finished_at=approval_finished_at,
                handler_started_at=handler_started_at,
                retryable=_retryable_failure(spec, exc=exc),
            )

        normalized = self._normalize(outcome, started_at)
        return replace(
            normalized,
            started_at=started_at,
            approval_started_at=approval_started_at,
            approval_finished_at=approval_finished_at,
            handler_started_at=handler_started_at,
            retryable=_retryable_from_result(spec, normalized),
        )

    async def execute_many_async(
        self,
        calls: Sequence[
            tuple[str, Mapping[str, object]]
            | tuple[str, str, Mapping[str, object]]
        ],
        *,
        source: UntrustedSource,
        intent: str = "",
        cancel_event: threading.Event | None = None,
    ) -> tuple[ToolResult, ...]:
        """Async batch execute using the same parallel policy as ``execute_many``."""
        if not calls:
            return ()
        normalized = tuple(self._normalize_call(call) for call in calls)

        async def _run_one(
            tool_call_id: str | None, name: str, arguments: Mapping[str, object]
        ) -> ToolResult:
            return await self.execute_async(
                name, arguments, source=source, intent=intent,
                cancel_event=cancel_event, tool_call_id=tool_call_id,
            )

        if not self._calls_are_parallel_safe(normalized):
            return tuple([
                await _run_one(tid, name, args) for tid, name, args in normalized
            ])
        results = await asyncio.gather(
            *(_run_one(tid, name, args) for tid, name, args in normalized)
        )
        return results


    @staticmethod
    def _invoke(
        handler: Callable[..., object],
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> object:
        results: queue.Queue[object] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                raw_result = handler(arguments)
                # Await if handler returned a coroutine (e.g. sync wrapper around async)
                if asyncio.iscoroutine(raw_result):
                    async def _async_call() -> object:
                        return await asyncio.wait_for(raw_result, timeout=timeout_seconds)
                    results.put(asyncio.run(_async_call()))
                else:
                    results.put(raw_result)
            except TimeoutError:
                results.put(_TIMED_OUT)
            except Exception as exc:
                results.put(
                    _HandlerFailure(retryable=isinstance(exc, _TRANSIENT_EXCEPTIONS))
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


def _timeout_warning(spec: ToolSpec) -> str:
    if spec.cancellation_class is CancellationClass.KILLABLE:
        return "The handler timed out; killable work should have been terminated."
    if spec.cancellation_class is CancellationClass.COOPERATIVE:
        return (
            "The handler timed out; cooperative cancellation was requested but "
            "the handler may still be unwinding."
        )
    return (
        "The handler did not finish before the deadline; an already running "
        "legacy operation may continue."
    )


def _retryable_failure(
    spec: ToolSpec, *, exc: BaseException | None = None, code: str | None = None
) -> bool:
    if not spec.idempotent:
        return False
    if exc is not None:
        return isinstance(exc, _TRANSIENT_EXCEPTIONS)
    if code is not None:
        return code in _TRANSIENT_CODES
    return False


def _retryable_from_result(spec: ToolSpec, result: ToolResult) -> bool:
    if result.ok:
        return False
    return _retryable_failure(spec, code=result.code) or (
        bool(result.retryable) and spec.idempotent and result.code in _TRANSIENT_CODES
    )


async def _invoke_handler_async(spec: ToolSpec, arguments: Mapping[str, object]) -> object:
    """Run a handler without blocking the event loop on sync callables."""
    sig = inspect.signature(spec.handler)
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )

    def _call() -> object:
        if has_var_keyword:
            return spec.handler(**arguments)
        return spec.handler(arguments)

    if inspect.iscoroutinefunction(spec.handler):
        raw_result = _call()
        return await asyncio.wait_for(raw_result, timeout=spec.timeout_seconds)

    raw_result = await asyncio.wait_for(
        asyncio.to_thread(_call), timeout=spec.timeout_seconds
    )
    if inspect.iscoroutine(raw_result):
        return await asyncio.wait_for(raw_result, timeout=spec.timeout_seconds)
    return raw_result


__all__ = ["ToolExecutor"]
