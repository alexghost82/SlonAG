"""Gemini Live adapter for the canonical tool registry and executor."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from mark.safety import SafetyDecision, SafetyPolicy, UntrustedSource
from mark.tools import ToolExecutor, ToolRegistry, ToolResult
from mark.tools.builtin import build_builtin_registry
from mark.tools.legacy.adapters import with_legacy_context


def build_live_registry(*, ui: Any, speak: Callable[[str], object]) -> ToolRegistry:
    """Bind UI compatibility context without changing canonical schemas."""
    registry = ToolRegistry()
    for spec in build_builtin_registry().list():
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
    ) -> None:
        self.ui = ui
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
        try:
            return bool(
                control_plane.request_approval(
                    decision.tool_name,
                    decision.args,
                    source="desktop_ui",
                    reason=decision.reason or "SafetyPolicy confirmation required",
                )
            )
        except Exception:
            return False

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        intent: str,
    ) -> ToolResult:
        checked = dict(arguments)
        if name == "file_processor" and not checked.get("file_path"):
            current_file = getattr(self.ui, "current_file", None)
            if current_file:
                checked["file_path"] = current_file
        return await asyncio.to_thread(
            self.executor.execute,
            name,
            checked,
            source=UntrustedSource.USER,
            intent=intent,
        )


__all__ = ["LiveToolBridge", "build_live_registry"]
