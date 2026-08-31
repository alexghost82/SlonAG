"""Gemini Live adapter for the canonical tool registry and executor."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from acta.safety import SafetyDecision, SafetyPolicy, UntrustedSource
from acta.tools import ToolExecutor, ToolRegistry, ToolResult
from acta.tools.builtin import build_builtin_registry
from acta.tools.legacy.adapters import with_legacy_context


def build_live_registry(
    *,
    ui: Any,
    speak: Callable[[str], object],
    base_registry: ToolRegistry | None = None,
) -> ToolRegistry:
    """Bind UI compatibility context without changing canonical schemas."""
    registry = ToolRegistry()
    source = base_registry or build_builtin_registry()
    for spec in source.list():
        registry.register(
            replace(
                spec,
                handler=with_legacy_context(spec.handler, speak=speak, player=ui),
            )
        )
    return registry


class LiveToolBridge:
    """Execute Live function calls through one fail-closed canonical pipeline."""

    def __init__(
        self,
        *,
        ui: Any,
        speak: Callable[[str], object],
        registry: ToolRegistry | None = None,
        policy: SafetyPolicy | None = None,
        approval_timeout_seconds: float = 30.0,
        dedupe_limit: int = 256,
    ) -> None:
        self.ui = ui
        self.approval_timeout_seconds = max(0.01, approval_timeout_seconds)
        self._dedupe_limit = max(1, dedupe_limit)
        self._calls: dict[str, asyncio.Future[ToolResult]] = {}
        self._calls_lock = asyncio.Lock()
        self.registry = registry or build_live_registry(ui=ui, speak=speak)
        self.executor = ToolExecutor(
            self.registry,
            policy or SafetyPolicy(),
            confirmer=self._confirm,
        )

    def _confirm(self, decision: SafetyDecision) -> bool:
        control_plane = getattr(self.ui, "control_plane", None)
        if control_plane is None:
            return False
        result: queue.Queue[bool] = queue.Queue(maxsize=1)

        def request() -> None:
            try:
                approved = bool(control_plane.request_approval(
                    decision.tool_name,
                    decision.args,
                    source="desktop_ui",
                    reason=decision.reason or "SafetyPolicy confirmation required",
                    tool_call_id=decision.tool_call_id,
                ))
            except Exception:
                approved = False
            try:
                result.put_nowait(approved)
            except queue.Full:
                pass

        threading.Thread(target=request, name="slon-approval", daemon=True).start()
        try:
            return result.get(timeout=self.approval_timeout_seconds)
        except queue.Empty:
            return False

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        intent: str,
        call_id: str | None = None,
    ) -> ToolResult:
        if not call_id:
            return await self._execute_once(
                name, arguments, intent=intent, tool_call_id=None
            )

        async with self._calls_lock:
            existing = self._calls.get(call_id)
            if existing is None:
                existing = asyncio.get_running_loop().create_future()
                self._calls[call_id] = existing
                owner = True
                while len(self._calls) > self._dedupe_limit:
                    oldest = next(iter(self._calls))
                    if oldest == call_id:
                        break
                    self._calls.pop(oldest)
            else:
                owner = False
        if not owner:
            return await asyncio.shield(existing)

        try:
            result = await self._execute_once(
                name, arguments, intent=intent, tool_call_id=call_id
            )
        except asyncio.CancelledError:
            result = ToolResult(
                ok=False,
                code="cancelled",
                message="Tool execution was cancelled.",
            )
            if not existing.done():
                existing.set_result(result)
            raise
        else:
            if not existing.done():
                existing.set_result(result)
            return result

    async def _execute_once(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        intent: str,
        tool_call_id: str | None,
    ) -> ToolResult:
        checked = dict(arguments)
        if name == "file_processor" and not checked.get("file_path"):
            current_file = getattr(self.ui, "current_file", None)
            if current_file:
                checked["file_path"] = current_file
        cancel_event = threading.Event()
        try:
            return await asyncio.to_thread(
                self.executor.execute,
                name,
                checked,
                source=UntrustedSource.USER,
                intent=intent,
                cancel_event=cancel_event,
                tool_call_id=tool_call_id,
            )
        except asyncio.CancelledError:
            cancel_event.set()
            raise


__all__ = ["LiveToolBridge", "build_live_registry"]
