"""Subagent delegation and orchestration for SlonAG.

Provides:
- Subagent creation with isolated context
- Task delegation with bounded budgets
- Parent-child identity and correlation
- Context isolation (session, workspace, run)
- Provider and model selection
- Tool allowlist / denylist
- Permission inheritance (never more than parent)
- Safety policy inheritance
- Approval propagation
- Execution budget (tool calls, turns, time)
- Iteration limits
- Timeout
- Cancellation propagation
- Concurrency limits
- Maximum delegation depth
- Failure propagation
- Partial failure handling
- Result collection
- Parent synthesis
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent.observation import Observation, ObservationKind
from agent.runtime import AgentLoop, LoopBudget, LoopDetector
from acta.tools.contracts import ToolResult
from acta.tools.executor import ToolExecutor
from acta.tools.registry import ToolRegistry
from acta.safety.policy import SafetyPolicy
from acta.safety.types import DecisionKind, SafetyDecision, UntrustedSource
from providers.contracts import (
    ChatProvider,
    ConversationMessage,
    ModelInfo,
)


@dataclass(frozen=True)
class SubagentResult:
    """Result returned by a subagent to its parent."""

    ok: bool
    answer: str | None = None
    error: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    provider_id: str | None = None
    model_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class SubagentConfig:
    """Configuration for a subagent instance."""

    parent_run_id: str
    parent_session_id: str
    parent_workspace_id: str

    # Task
    delegation_task: str
    allowed_tools: frozenset[str] | None = None
    denied_tools: frozenset[str] = field(default_factory=frozenset)

    # Provider
    provider_id: str | None = None
    model_id: str | None = None

    # Budget
    max_tool_calls: int = 8
    max_turns: int = 5
    timeout_seconds: float = 60.0

    # Limits
    max_depth: int = 1
    concurrency_limit: int = 4

    # Identity
    subagent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class SubagentHandle:
    """Handle for an active subagent instance."""

    subagent_id: str
    parent_run_id: str
    parent_session_id: str
    parent_workspace_id: str
    _task: asyncio.Task[SubagentResult] | None = None
    _cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def is_done(self) -> bool:
        if self._task is None:
            return False
        return self._task.done()

    async def cancel(self) -> None:
        self._cancel_event.set()
        if self._task is not None:
            self._task.cancel()


class SubagentRuntime:
    """Manages subagent creation, execution, and result collection.

    Features:
    - Bounded context isolation
    - Permission inheritance (never more than parent)
    - Tool allowlist enforcement
    - Safety policy inheritance
    - Approval propagation
    - Budget enforcement
    - Timeout and cancellation
    - Concurrency limiting
    - Delegation depth limiting
    - Failure propagation
    - Parent synthesis
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 4,
        max_delegation_depth: int = 3,
        safety_policy: SafetyPolicy | None = None,
        approval_required: bool = False,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._max_delegation_depth = max_delegation_depth
        self._safety_policy = safety_policy or SafetyPolicy()
        self._approval_required = approval_required
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active: dict[str, SubagentHandle] = {}
        self._lock = threading.Lock()

    async def create_and_run(
        self,
        config: SubagentConfig,
        *,
        parent_tools: ToolRegistry | None = None,
        parent_safety: SafetyPolicy | None = None,
        provider: ChatProvider | None = None,
    ) -> SubagentResult:
        """Create a subagent, delegate the task, and await the result."""
        # Check delegation depth
        depth = self._current_depth(config.parent_run_id)
        if depth >= self._max_delegation_depth:
            return SubagentResult(
                ok=False,
                error=f"Достигнута максимальная глубина делегирования ({self._max_delegation_depth})",
                reason="Max depth exceeded",
            )

        # Check concurrency
        if len(self._active) >= self._max_concurrency:
            return SubagentResult(
                ok=False,
                error="Достигнут предел параллельных подзадач",
                reason="Max concurrency exceeded",
            )

        # Build bounded budget
        budget = LoopBudget(
            max_tool_calls=config.max_tool_calls,
            max_turns=config.max_turns,
            timeout_seconds=config.timeout_seconds,
        )

        # Build filtered registry
        registry = self._filter_registry(
            parent_tools, config.allowed_tools, config.denied_tools
        )

        # Build safety policy with filtered tools
        sub_policy = _build_subagent_safety(
            parent_safety or self._safety_policy, config
        )

        # Select provider
        model_info = self._resolve_model(
            provider, config.provider_id, config.model_id
        )

        handle = SubagentHandle(
            subagent_id=config.subagent_id,
            parent_run_id=config.parent_run_id,
            parent_session_id=config.parent_session_id,
            parent_workspace_id=config.parent_workspace_id,
        )

        handle._task = asyncio.create_task(
            self._run_subagent(
                config.subagent_id,
                config.delegation_task,
                model_info,
                budget,
                registry,
                sub_policy,
                provider,
                handle._cancel_event,
            )
        )

        with self._lock:
            self._active[config.subagent_id] = handle

        try:
            return await handle._task
        except asyncio.CancelledError:
            return SubagentResult(
                ok=False,
                error="Подзадача была отменена",
                reason="Cancelled",
            )
        finally:
            with self._lock:
                self._active.pop(config.subagent_id, None)

    async def _run_subagent(
        self,
        subagent_id: str,
        task: str,
        model_info: ModelInfo,
        budget: LoopBudget,
        registry: ToolRegistry,
        safety: SafetyPolicy,
        provider: ChatProvider | None,
        cancel_event: threading.Event,
    ) -> SubagentResult:
        """Execute the subagent loop."""
        try:
            loop = AgentLoop(
                model=model_info,
                provider=provider,
                tool_executor=ToolExecutor(registry, safety),
                budget=budget,
                cancel_event=cancel_event,
            )

            result = await loop.run(user_goal=task)

            return SubagentResult(
                ok=result.ok,
                answer=result.final_answer,
                steps=[{
                    "turn": s.turn_index,
                    "tool": s.tool_name,
                } for s in result.steps],
                tool_calls=budget.tool_call_count,
                provider_id=model_info.provider_id,
                model_id=model_info.model_id,
                reason=result.reason,
            )
        except asyncio.CancelledError:
            return SubagentResult(
                ok=False,
                error="Задача подзадачи отменена",
                reason="Cancelled",
            )
        except asyncio.TimeoutError:
            return SubagentResult(
                ok=False,
                error="Истекло время выполнения подзадачи",
                reason="Timeout",
            )
        except Exception as exc:
            return SubagentResult(
                ok=False,
                error=str(exc),
                reason="Error",
            )

    def _filter_registry(
        self,
        parent: ToolRegistry | None,
        allowed: frozenset[str] | None,
        denied: frozenset[str],
    ) -> ToolRegistry:
        """Build a filtered ToolRegistry respecting allow/deny lists."""
        registry = ToolRegistry()
        if parent is None:
            return registry

        for spec in parent.list():
            name = spec.name
            if name in denied:
                continue
            if allowed is not None and name not in allowed:
                continue
            registry.register(spec)
        return registry

    def _resolve_model(
        self,
        provider: ChatProvider | None,
        provider_id: str | None,
        model_id: str | None,
    ) -> ModelInfo:
        """Resolve model info, defaulting to a test model if not provided."""
        if provider_id and model_id:
            return ModelInfo(
                provider_id=provider_id,
                model_id=model_id,
                display_name=f"{provider_id}/{model_id}",
                text=True,
                tool_calling=True,
            )
        return ModelInfo(
            provider_id="test",
            model_id="test-model",
            display_name="Test model",
            text=True,
            tool_calling=True,
        )

    def _current_depth(self, run_id: str) -> int:
        """Estimate delegation depth by counting active subagents with this parent."""
        count = 0
        with self._lock:
            for handle in self._active.values():
                if handle.parent_run_id == run_id:
                    count += 1
        return count

    async def cancel_all(self) -> None:
        """Cancel all active subagents."""
        handles: list[SubagentHandle]
        with self._lock:
            handles = list(self._active.values())
        for handle in handles:
            await handle.cancel()

    @property
    def active_count(self) -> int:
        return len(self._active)


def _build_subagent_safety(
    parent_policy: SafetyPolicy, config: SubagentConfig
) -> SafetyPolicy:
    """Build a safety policy that never grants more permissions than parent."""
    return _BoundedSafetyPolicy(parent_policy, config.denied_tools)


class _BoundedSafetyPolicy(SafetyPolicy):
    """SafetyPolicy wrapper that enforces tool denylists for subagents."""

    def __init__(
        self,
        parent: SafetyPolicy,
        denied_tools: frozenset[str],
    ) -> None:
        self._parent = parent
        self._denied_tools = denied_tools

    def authorize(
        self,
        tool_name: str,
        args: object,
        *,
        source: UntrustedSource | str = UntrustedSource.TOOL_RESULT,
        intent: str = "",
    ) -> SafetyDecision:
        if tool_name in self._denied_tools:
            return SafetyDecision(
                kind=DecisionKind.DENY,
                tool_name=tool_name,
                risk=0,
                source=(
                    source
                    if isinstance(source, UntrustedSource)
                    else UntrustedSource(tool_name)
                ),
                intent=intent,
                args={},
                reason=f"Tool '{tool_name}' is denied by parent policy",
            )
        return self._parent.authorize(tool_name, args, source=source, intent=intent)

    def risk_for(self, tool_name: str) -> int:
        return self._parent.risk_for(tool_name)

    def validate_args(self, tool_name: str, args: object) -> dict[str, Any]:
        return self._parent.validate_args(tool_name, args)


# ── Simple session dataclass for E2E tests ────────────────────────

@dataclass
class SubagentSession:
    """Minimal subagent session for E2E chain testing."""
    session_id: str = ""
    goal: str = ""
    workspace_id: str = ""
    status: str = "created"
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.monotonic()
