"""Iterative Multi-Turn Agent Loop Runtime (Wave 15)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from agent.observation import Observation, ObservationKind
from agent.latency import LatencyTrace
from agent.steering import SteeringKind, SteeringQueue, SteeringSignal
from mark.tools.contracts import ToolResult
from providers.contracts import (
    AssistantMessage,
    AssistantToolCallMessage,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    ConversationMessage,
    ModelInfo,
    ToolResultMessage,
    ToolCall,
    ToolDefinition,
    UserMessage,
)


@dataclass
class LoopBudget:
    """Tracks and enforces limits on agent loop turns, tool calls, and wall-clock execution time."""

    max_tool_calls: int = 15
    max_turns: int = 10
    timeout_seconds: float = 120.0
    tool_call_count: int = 0
    turn_count: int = 0
    start_time: float = field(default_factory=time.time)

    def is_exceeded(self) -> tuple[bool, str | None]:
        """Check if any budget threshold has been exceeded."""
        if self.tool_call_count >= self.max_tool_calls:
            return True, f"Max tool calls ({self.max_tool_calls}) reached"
        if self.turn_count >= self.max_turns:
            return True, f"Max turns ({self.max_turns}) reached"
        elapsed = time.time() - self.start_time
        if elapsed >= self.timeout_seconds:
            return True, f"Timeout ({self.timeout_seconds:.1f}s) exceeded"
        return False, None

    def remaining_seconds(self) -> float:
        """Return the positive wall-clock allowance left for an awaited operation."""
        return max(0.0, self.timeout_seconds - (time.time() - self.start_time))


class LoopDetector:
    """Detects runaway tool call loops, including repetitions, oscillations, and zero progress."""

    def __init__(
        self,
        max_consecutive: int = 3,
        max_oscillating: int = 3,
        max_zero_progress: int = 3,
    ) -> None:
        self.history: list[dict[str, Any]] = []
        self.max_consecutive = max_consecutive
        self.max_oscillating = max_oscillating
        self.max_zero_progress = max_zero_progress

    def record_call(
        self, tool_name: str, args: dict, result_summary: str | None = None
    ) -> None:
        """Record an executed tool call for loop detection analysis."""
        canonical_args = (
            json.dumps(args, sort_keys=True, default=str)
            if isinstance(args, dict)
            else str(args)
        )
        self.history.append(
            {
                "tool_name": tool_name,
                "args": args,
                "canonical_args": canonical_args,
                "result_summary": result_summary,
            }
        )

    def check_loop(self) -> tuple[bool, str | None]:
        """Analyze history for repetitive loops, oscillating calls, or zero-progress cycles."""
        if not self.history:
            return False, None

        # 1. Consecutive N>=3 identical tool calls with same arguments
        if len(self.history) >= self.max_consecutive:
            last_n = self.history[-self.max_consecutive :]
            first_key = (last_n[0]["tool_name"], last_n[0]["canonical_args"])
            if all(
                (item["tool_name"], item["canonical_args"]) == first_key
                for item in last_n
            ):
                return (
                    True,
                    f"Detected {self.max_consecutive} consecutive identical tool calls for '{first_key[0]}'",
                )

        # 2. Oscillating call patterns (e.g., A/B/A/B/A/B)
        pattern_len = self.max_oscillating * 2
        if len(self.history) >= pattern_len:
            window = self.history[-pattern_len:]
            keys = [(item["tool_name"], item["canonical_args"]) for item in window]
            if (
                keys[0] == keys[2] == keys[4]
                and keys[1] == keys[3] == keys[5]
                and keys[0] != keys[1]
            ):
                return True, "Detected oscillating call pattern (A/B/A/B/A/B)"

        # 3. Zero-progress repetition loops
        call_result_counts: dict[tuple[str, str, str | None], int] = {}
        for entry in self.history:
            if entry["result_summary"] is not None:
                key = (
                    entry["tool_name"],
                    entry["canonical_args"],
                    entry["result_summary"],
                )
                call_result_counts[key] = call_result_counts.get(key, 0) + 1
                if call_result_counts[key] >= self.max_zero_progress:
                    return (
                        True,
                        f"Detected zero-progress repetition loop for '{entry['tool_name']}'",
                    )

        return False, None


@dataclass
class AgentLoopStepResult:
    """Result of a single step within an agent execution turn."""

    turn_index: int
    tool_name: str | None = None
    observation: Observation | None = None
    steering: SteeringSignal | None = None


@dataclass
class AgentLoopResult:
    """Final outcome of an AgentLoop execution."""

    ok: bool
    final_answer: str | None = None
    steps: list[AgentLoopStepResult] = field(default_factory=list)
    reason: str = ""
    latency_ms: dict[str, float] = field(default_factory=dict)


class AgentLoop:
    """Core multi-turn model -> tool -> observation -> model orchestration engine."""

    def __init__(
        self,
        *,
        model: ModelInfo,
        provider: ChatProvider | None = None,
        tool_executor: Any = None,
        budget: LoopBudget | None = None,
        loop_detector: LoopDetector | None = None,
    ) -> None:
        self.provider = provider
        self.tool_executor = tool_executor
        if not isinstance(model, ModelInfo):
            raise TypeError("model must be an explicitly selected ModelInfo")
        self.model = model
        self.budget = budget if budget is not None else LoopBudget()
        self.loop_detector = (
            loop_detector if loop_detector is not None else LoopDetector()
        )

    async def run(
        self,
        user_goal: str,
        steering_queue: SteeringQueue | None = None,
    ) -> AgentLoopResult:
        """Executes the multi-turn agent loop until a final answer or termination condition is reached."""
        steps: list[AgentLoopStepResult] = []
        trace = LatencyTrace()
        messages: list[ConversationMessage] = [UserMessage(user_goal)]

        while True:
            exceeded, reason = self.budget.is_exceeded()
            if exceeded:
                return AgentLoopResult(
                    ok=False,
                    final_answer=None,
                    steps=steps,
                    reason=reason or "Budget exceeded",
                )

            # Check steering queue at start of turn
            if steering_queue is not None and not steering_queue.is_empty():
                signal = steering_queue.pop_highest_priority()
                if signal is not None:
                    steps.append(
                        AgentLoopStepResult(
                            turn_index=self.budget.turn_count,
                            steering=signal,
                        )
                    )
                    if signal.kind in (
                        SteeringKind.SYSTEM_CANCEL,
                        SteeringKind.USER_INTERRUPT,
                    ):
                        return AgentLoopResult(
                            ok=False,
                            final_answer=None,
                            steps=steps,
                            reason=f"Cancelled by steering signal: {signal.kind.value}",
                        )
                    if signal.kind in (
                        SteeringKind.USER_GUIDANCE,
                        SteeringKind.VOICE_INTERRUPTION,
                    ):
                        text = signal.text or "User guidance injected"
                        messages.append(UserMessage(text))

            if self.budget.turn_count >= self.budget.max_turns:
                return AgentLoopResult(False, steps=steps, reason=f"Max turns ({self.budget.max_turns}) reached")
            self.budget.turn_count += 1

            # Dispatch call to model provider
            try:
                trace.mark("provider_request_start")
                response = await asyncio.wait_for(
                    self._call_provider(messages), timeout=self.budget.remaining_seconds()
                )
            except TimeoutError:
                return AgentLoopResult(False, steps=steps, reason=f"Timeout ({self.budget.timeout_seconds:.1f}s) exceeded")
            except asyncio.CancelledError:
                raise
            trace.mark("provider_first_response")

            if not isinstance(response, ChatResponse):
                raise TypeError("provider.chat() must return ChatResponse")
            response_text = response.text
            tool_calls = response.tool_calls
            duplicate_ids = _duplicate_tool_call_ids(tool_calls)
            if duplicate_ids:
                return AgentLoopResult(
                    ok=False,
                    final_answer=None,
                    steps=steps,
                    reason=f"Duplicate tool_call_id: {duplicate_ids[0]}",
                )
            if tool_calls:
                messages.append(
                    AssistantToolCallMessage(
                        content=response_text,
                        tool_calls=tool_calls,
                    )
                )
            else:
                messages.append(AssistantMessage(response_text))

            if not tool_calls:
                trace.mark("turn_complete")
                return AgentLoopResult(
                    ok=True,
                    final_answer=str(response_text) if response_text else None,
                    steps=steps,
                    reason="Completed successfully",
                    latency_ms=trace.breakdown(),
                )

            parsed_calls = [self._parse_tool_call(call) for call in tool_calls]
            remaining_calls = max(
                0, self.budget.max_tool_calls - self.budget.tool_call_count
            )
            batch_results: tuple[object, ...] | None = None
            if hasattr(self.tool_executor, "execute_many") and remaining_calls:
                from mark.safety import UntrustedSource

                selected = parsed_calls[:remaining_calls]
                try:
                    trace.mark("tool_call_received")
                    trace.mark("tool_execution_start")
                    batch_results = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.tool_executor.execute_many,
                            [(name, args) for _id, name, args in selected],
                            source=UntrustedSource.USER,
                            intent=user_goal,
                        ),
                        timeout=self.budget.remaining_seconds(),
                    )
                except TimeoutError:
                    return AgentLoopResult(
                        False,
                        steps=steps,
                        reason=f"Timeout ({self.budget.timeout_seconds:.1f}s) exceeded",
                    )

            for call_index, tool_call in enumerate(tool_calls):
                if self.budget.tool_call_count >= self.budget.max_tool_calls:
                    return AgentLoopResult(
                        ok=False,
                        final_answer=str(response_text) if response_text else None,
                        steps=steps,
                        reason=f"Max tool calls ({self.budget.max_tool_calls}) reached",
                    )
                self.budget.tool_call_count += 1

                tool_id, tool_name, tool_args = parsed_calls[call_index]

                # Execute tool, returning observation on error instead of crashing
                try:
                    if batch_results is not None:
                        raw_res = batch_results[call_index]
                    else:
                        raw_res = await asyncio.wait_for(
                            self._execute_tool(tool_name, tool_args, user_goal),
                            timeout=self.budget.remaining_seconds(),
                        )
                    if isinstance(raw_res, Observation):
                        obs = raw_res
                    elif isinstance(raw_res, ToolResult):
                        obs = Observation.from_tool_result(tool_id, tool_name, raw_res)
                    else:
                        obs = Observation(
                            tool_call_id=tool_id,
                            tool_name=tool_name,
                            kind=ObservationKind.SUCCESS,
                            ok=True,
                            content=raw_res,
                        )
                except TimeoutError:
                    obs = Observation(
                        tool_call_id=tool_id,
                        tool_name=tool_name,
                        kind=ObservationKind.TIMEOUT,
                        ok=False,
                        error="Tool execution timed out.",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    obs = Observation(
                        tool_call_id=tool_id,
                        tool_name=tool_name,
                        kind=ObservationKind.TOOL_ERROR,
                        ok=False,
                        error=str(exc),
                    )
                trace.mark("tool_execution_finish")

                step_res = AgentLoopStepResult(
                    turn_index=self.budget.turn_count,
                    tool_name=tool_name,
                    observation=obs,
                )
                steps.append(step_res)

                summary = str(obs.content) if obs.ok else (obs.error or "Error")
                self.loop_detector.record_call(
                    tool_name, tool_args, result_summary=summary
                )

                is_loop, loop_reason = self.loop_detector.check_loop()
                if is_loop and self.budget.turn_count < self.budget.max_turns:
                    return AgentLoopResult(
                        ok=False,
                        final_answer=None,
                        steps=steps,
                        reason=loop_reason or "Loop detected",
                    )

                messages.append(
                    ToolResultMessage(
                        tool_call_id=tool_id,
                        tool_name=tool_name,
                        result=obs.content if obs.ok else None,
                        error=None if obs.ok else obs.error,
                        artifacts=tuple(obs.artifacts),
                    )
                )
                trace.mark("observation_returned")

            if self.budget.turn_count >= self.budget.max_turns:
                return AgentLoopResult(
                    ok=False,
                    final_answer=str(response_text) if response_text else None,
                    steps=steps,
                    reason=f"Max turns ({self.budget.max_turns}) reached",
                )

            # Check steering queue after observation processing
            if steering_queue is not None and not steering_queue.is_empty():
                signal = steering_queue.pop_highest_priority()
                if signal is not None:
                    steps.append(
                        AgentLoopStepResult(
                            turn_index=self.budget.turn_count,
                            steering=signal,
                        )
                    )
                    if signal.kind in (
                        SteeringKind.SYSTEM_CANCEL,
                        SteeringKind.USER_INTERRUPT,
                    ):
                        return AgentLoopResult(
                            ok=False,
                            final_answer=None,
                            steps=steps,
                            reason=f"Cancelled by steering signal: {signal.kind.value}",
                        )
                    if signal.kind in (
                        SteeringKind.USER_GUIDANCE,
                        SteeringKind.VOICE_INTERRUPTION,
                    ):
                        text = signal.text or "User guidance injected"
                        messages.append(UserMessage(text))

    async def _call_provider(self, messages: list[ConversationMessage]) -> ChatResponse:
        if self.provider is None:
            raise RuntimeError("No ChatProvider configured")
        specs = getattr(
            getattr(self.tool_executor, "registry", None), "list", lambda: ()
        )()
        tools = (
            tuple(
                ToolDefinition(spec.name, spec.description, spec.input_schema)
                for spec in specs
            )
            if self.model.tool_calling
            else ()
        )
        req = ChatRequest(model=self.model, messages=tuple(messages), tools=tools)
        response = await self.provider.chat(req)
        if not isinstance(response, ChatResponse):
            raise TypeError("provider.chat() must return ChatResponse")
        return response

    async def _execute_tool(
        self, tool_name: str, args: dict, goal: str
    ) -> Any:
        executor = self.tool_executor
        if executor is None:
            try:
                from mark.safety import SafetyPolicy
                from mark.tools import ToolExecutor
                from mark.tools.builtin import build_builtin_registry

                executor = ToolExecutor(build_builtin_registry(), SafetyPolicy())
            except Exception:
                raise RuntimeError("No tool_executor provided and default cannot be built.")

        if hasattr(executor, "execute"):
            from mark.safety import UntrustedSource

            res = await asyncio.to_thread(
                executor.execute,
                tool_name,
                args,
                source=UntrustedSource.USER,
                intent=goal,
            )
        elif callable(executor):
            res = executor(tool_name, args)
        else:
            raise RuntimeError(f"Unsupported tool_executor type: {type(executor)}")

        if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
            res = await res

        return res

    @staticmethod
    def _parse_tool_call(tool_call: ToolCall) -> tuple[str, str, dict]:
        if not isinstance(tool_call, ToolCall):
            raise TypeError("provider tool calls must use canonical ToolCall")
        return tool_call.id, tool_call.name, dict(tool_call.arguments)


def _duplicate_tool_call_ids(tool_calls: Sequence[ToolCall]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for call in tool_calls:
        if call.id in seen and call.id not in duplicates:
            duplicates.append(call.id)
        seen.add(call.id)
    return tuple(duplicates)
