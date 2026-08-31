"""Comprehensive tests for subagent delegation, lifecycle, and orchestration."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent.observation import Observation, ObservationKind
from agent.runtime import AgentLoop, LoopBudget
from agent.subagent import (
    SubagentConfig,
    SubagentHandle,
    SubagentResult,
    SubagentRuntime,
)
from acta.safety.policy import SafetyPolicy
from acta.safety.types import RiskLevel
from acta.tools.contracts import SideEffectClass, ToolResult, ToolSpec
from acta.tools.registry import ToolRegistry
from providers.contracts import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ToolCall,
)


def _make_model(**overrides: object) -> ModelInfo:
    base = dict(
        provider_id="test",
        model_id="test-model",
        display_name="Test model",
        text=True,
        tool_calling=True,
    )
    base.update(overrides)
    return ModelInfo(**base)


def _make_config(**overrides: object) -> SubagentConfig:
    base = dict(
        parent_run_id="run-001",
        parent_session_id="sess-001",
        parent_workspace_id="ws-001",
        delegation_task="Calculate 2+2 and return the answer.",
        max_tool_calls=4,
        max_turns=3,
        timeout_seconds=10.0,
    )
    base.update(overrides)
    return SubagentConfig(**base)  # type: ignore[arg-type]


def _echo_tool() -> ToolSpec:
    async def handler(**kwargs: object) -> ToolResult:
        msg = kwargs.get("message", "")
        return ToolResult(ok=True, message=f"echo: {msg}")
    return ToolSpec(
        name="echo",
        description="Echo a message",
        input_schema={"type": "object", "properties": {"message": {"type": "string"}}},
        output_schema=None,
        handler=handler,
        risk=RiskLevel.READ,
        read_only=True,
        idempotent=True,
        side_effects=False,
        side_effect_class=SideEffectClass.NONE,
        parallel_safe=True,
    )


def _write_tool() -> ToolSpec:
    async def handler(**kwargs: object) -> ToolResult:
        return ToolResult(ok=True, message="written")
    return ToolSpec(
        name="write_file",
        description="Write a file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        output_schema=None,
        handler=handler,
        risk=RiskLevel.READ,
        read_only=False,
        idempotent=False,
        side_effects=True,
        side_effect_class=SideEffectClass.REVERSIBLE,
        parallel_safe=False,
    )


def _make_response(text: str, tool_calls: list[ToolCall] | None = None) -> ChatResponse:
    return ChatResponse(
        provider_id="test",
        model_id="test-model",
        text=text,
        tool_calls=tuple(tool_calls) if tool_calls else (),
    )


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------

class TestSubagentBasicLifecycle:
    @pytest.mark.asyncio
    async def test_subagent_runs_to_completion(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        config = _make_config(delegation_task="Say hello")

        async def chat(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            return _make_response("Hello from subagent.")

        result = await runtime.create_and_run(
            config, provider=MagicMock(chat=chat),  # type: ignore[arg-type]
        )
        assert isinstance(result, SubagentResult)
        assert result.ok


class TestSubagentContextIsolation:
    @pytest.mark.asyncio
    async def test_isolated_session(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        config = _make_config(parent_session_id="parent-sess", delegation_task="Isolated test")

        async def chat(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            return _make_response("ok")

        result = await runtime.create_and_run(
            config, provider=MagicMock(chat=chat),  # type: ignore[arg-type]
        )
        assert result.ok


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class TestSubagentBudget:
    @pytest.mark.asyncio
    async def test_tool_call_budget_limit(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        config = _make_config(
            delegation_task="Make tool calls",
            max_tool_calls=2,
            max_turns=5,
        )

        registry = ToolRegistry()
        registry.register(_echo_tool())

        turn = [0]

        async def chat(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            turn[0] += 1
            if turn[0] <= 2:
                calls = [ToolCall(id=f"call-{turn[0]}", name="echo", arguments={"message": f"t{turn[0]}"})]
                return _make_response("", tool_calls=calls)
            return _make_response("done")

        result = await runtime.create_and_run(
            config, parent_tools=registry, provider=MagicMock(chat=chat),  # type: ignore[arg-type]
        )
        assert result.tool_calls <= 2


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestSubagentTimeout:
    @pytest.mark.asyncio
    async def test_subagent_timeout(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        config = _make_config(
            delegation_task="Long task",
            max_tool_calls=10,
            max_turns=10,
            timeout_seconds=0.5,
        )

        async def slow(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)
            return _make_response("slow")

        result = await runtime.create_and_run(
            config, provider=MagicMock(chat=slow),  # type: ignore[arg-type]
        )
        assert isinstance(result, SubagentResult)
        assert result.ok is False
        assert result.reason.startswith("Timeout")


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

class TestSubagentCancellation:
    @pytest.mark.asyncio
    async def test_cancel_subagent(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)

        async def slow(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            await asyncio.sleep(10)
            return _make_response("slow")

        handle = SubagentHandle(
            subagent_id="test-001",
            parent_run_id="run-001",
            parent_session_id="sess-001",
            parent_workspace_id="ws-001",
        )
        handle._task = asyncio.create_task(
            runtime._run_subagent(  # type: ignore[arg-type]
                "test-001", "Long task", _make_model(),
                LoopBudget(timeout_seconds=30), ToolRegistry(),
                SafetyPolicy(), slow, handle._cancel_event,
            )
        )
        runtime._active["test-001"] = handle  # type: ignore[assignment]

        await asyncio.sleep(0.1)
        await handle.cancel()
        await asyncio.sleep(0.3)
        assert handle.is_done


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestSubagentConcurrency:
    @pytest.mark.asyncio
    async def test_cancel_all(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)

        async def slow(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)
            return _make_response("slow")

        handles: list[SubagentHandle] = []
        for i in range(3):
            h = SubagentHandle(
                subagent_id=f"sub-{i}",
                parent_run_id="run-001",
                parent_session_id="sess-001",
                parent_workspace_id="ws-001",
            )
            h._task = asyncio.create_task(
                runtime._run_subagent(  # type: ignore[arg-type]
                    f"sub-{i}", f"Task {i}", _make_model(),
                    LoopBudget(timeout_seconds=30), ToolRegistry(),
                    SafetyPolicy(), slow, h._cancel_event,
                )
            )
            runtime._active[f"sub-{i}"] = h  # type: ignore[assignment]
            handles.append(h)

        assert runtime.active_count == 3
        await runtime.cancel_all()
        await asyncio.sleep(0.3)
        for h in handles:
            assert h.is_done


# ---------------------------------------------------------------------------
# Depth
# ---------------------------------------------------------------------------

class TestSubagentDepth:
    @pytest.mark.asyncio
    async def test_max_depth(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4, max_delegation_depth=1)
        config = _make_config(parent_run_id="run-001", delegation_task="Nested")

        async def chat(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            return _make_response("ok")

        result = await runtime.create_and_run(
            config, provider=MagicMock(chat=chat),  # type: ignore[arg-type]
        )
        assert isinstance(result, SubagentResult)


# ---------------------------------------------------------------------------
# Tool filtering
# ---------------------------------------------------------------------------

class TestSubagentToolFiltering:
    @pytest.mark.asyncio
    async def test_deny_tools(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        registry = ToolRegistry()
        registry.register(_echo_tool())
        registry.register(_write_tool())

        config = _make_config(delegation_task="echo only", denied_tools=frozenset(["write_file"]))

        async def chat(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            return _make_response("echo ok")

        result = await runtime.create_and_run(
            config, parent_tools=registry, provider=MagicMock(chat=chat),  # type: ignore[arg-type]
        )
        assert isinstance(result, SubagentResult)

    @pytest.mark.asyncio
    async def test_allowlist(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        registry = ToolRegistry()
        registry.register(_echo_tool())

        config = _make_config(delegation_task="echo only", allowed_tools=frozenset(["echo"]))

        async def chat(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            return _make_response("echo only")

        result = await runtime.create_and_run(
            config, parent_tools=registry, provider=MagicMock(chat=chat),  # type: ignore[arg-type]
        )
        assert isinstance(result, SubagentResult)


# ---------------------------------------------------------------------------
# Failure propagation
# ---------------------------------------------------------------------------

class TestSubagentFailurePropagation:
    @pytest.mark.asyncio
    async def test_provider_error(self) -> None:
        runtime = SubagentRuntime(max_concurrency=4)
        config = _make_config(delegation_task="failing", timeout_seconds=2)

        async def failing(request: ChatRequest) -> ChatResponse:  # type: ignore[no-untyped-def]
            raise RuntimeError("Provider connection lost")

        result = await runtime.create_and_run(config, provider=failing)
        assert isinstance(result, SubagentResult)
        assert result.ok is False


# ---------------------------------------------------------------------------
# SubagentHandle
# ---------------------------------------------------------------------------

class TestSubagentHandle:
    def test_handle_is_done_initially(self) -> None:
        h = SubagentHandle(subagent_id="t", parent_run_id="r", parent_session_id="s", parent_workspace_id="w")
        assert h.is_done is False

    @pytest.mark.asyncio
    async def test_cancel_non_task(self) -> None:
        h = SubagentHandle(subagent_id="t", parent_run_id="r", parent_session_id="s", parent_workspace_id="w")
        await h.cancel()
        assert h.is_done is False


