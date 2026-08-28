"""Iterative Multi-Turn Agent Loop Runtime (Wave 15)."""

from __future__ import annotations

import asyncio
import json
import time
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.observation import Observation, ObservationKind
from agent.latency import LatencyTrace
from i18n import t
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
    effective_provider_id: str | None = None
    effective_model_id: str | None = None


class MemoryContextCallback(Protocol):
    """Protocol for memory context injection hooks."""

    def __call__(self, user_input: str) -> str: ...


class AgentLoop:
    """Core multi-turn model -> tool -> observation -> model orchestration engine.

    Supports memory integration via optional callbacks:
    - memory_context_callback: returns memory context text to prepend to messages
    - memory_on_turn_complete: called after each turn with (user_input, assistant_output)
    """

    def __init__(
        self,
        *,
        model: ModelInfo,
        provider: ChatProvider | None = None,
        tool_executor: Any = None,
        budget: LoopBudget | None = None,
        loop_detector: LoopDetector | None = None,
        cancel_event: threading.Event | None = None,
        memory_context_callback: MemoryContextCallback | None = None,
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
        self.cancel_event = cancel_event
        self._memory_callback = memory_context_callback

    async def run(
        self,
        user_goal: str,
        steering_queue: SteeringQueue | None = None,
        *,
        history: Sequence[ConversationMessage] = (),
        on_message: Callable[[ConversationMessage], None] | None = None,
        on_turn_complete: Callable[[str, str], None] | None = None,
    ) -> AgentLoopResult:
        """Executes the multi-turn agent loop until a final answer or termination condition is reached."""
        steps: list[AgentLoopStepResult] = []
        trace = LatencyTrace()
        messages: list[ConversationMessage] = list(history)

        def append_message(message: ConversationMessage) -> None:
            messages.append(message)
            if on_message is not None:
                on_message(message)

        append_message(UserMessage(user_goal))

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
                        append_message(UserMessage(text))

            if self.budget.turn_count >= self.budget.max_turns:
                return AgentLoopResult(False, steps=steps, reason=f"Max turns ({self.budget.max_turns}) reached")
            self.budget.turn_count += 1

            # Dispatch call to model provider
            try:
                trace.mark("provider_request_start")
                response = await asyncio.wait_for(
                    self._call_provider(messages, user_goal), timeout=self.budget.remaining_seconds()
                )
            except TimeoutError:
                return AgentLoopResult(False, steps=steps, reason=f"Timeout ({self.budget.timeout_seconds:.1f}s) exceeded")
            except asyncio.CancelledError:
                raise
            trace.mark("provider_first_response")

            if not (hasattr(response, "text") and hasattr(response, "tool_calls") and hasattr(response, "provider_id") and hasattr(response, "model_id")):
                raise TypeError("provider.chat() must return an object with text, tool_calls, provider_id, model_id attributes")
            response_text = response.text
            tool_calls = response.tool_calls
            duplicate_ids = _duplicate_tool_call_ids(tool_calls)
            if duplicate_ids:
                return AgentLoopResult(
                    ok=False,
                    final_answer=None,
                    steps=steps,
                    reason=f"Duplicate tool call IDs detected: {duplicate_ids}",
                )

            if tool_calls:
                self.budget.tool_call_count += 1

                # Record for loop detection
                for tc in tool_calls:
                    self.loop_detector.record_call(tc.name, dict(tc.arguments))

                # Check loop before executing
                loop_detected, loop_reason = self.loop_detector.check_loop()
                if loop_detected:
                    return AgentLoopResult(
                        ok=False,
                        steps=steps,
                        reason=loop_reason or "Loop detected",
                    )

                observations: list[Observation] = []
                tool_result_messages: list[ToolResultMessage] = []
                for tool_call in tool_calls:
                    tool_id = tool_call.id
                    tool_name = tool_call.name
                    args = dict(tool_call.arguments)

                    if self.cancel_event is not None and self.cancel_event.is_set():
                        observations.append(
                            Observation(
                                tool_call_id=tool_id,
                                tool_name=tool_name,
                                kind=ObservationKind.TOOL_ERROR,
                                content="Cancelled",
                                ok=False,
                                error="Tool execution cancelled",
                            )
                        )
                        tool_result_messages.append(
                            ToolResultMessage(
                                tool_call_id=tool_id,
                                tool_name=tool_name,
                                result="Cancelled",
                                error="Tool execution cancelled",
                            )
                        )
                        continue

                    trace.mark("tool_execution_start")
                    try:
                        exec_result = await self._execute_tool(tool_id, tool_name, args, user_goal)
                    except Exception as exc:
                        observations.append(
                            Observation(
                                tool_call_id=tool_id,
                                tool_name=tool_name,
                                kind=ObservationKind.TOOL_ERROR,
                                content=str(exc),
                                ok=False,
                                error=str(exc),
                            )
                        )
                        tool_result_messages.append(
                            ToolResultMessage(
                                tool_call_id=tool_id,
                                tool_name=tool_name,
                                result=None,
                                error=str(exc),
                            )
                        )
                        continue

                    trace.mark("tool_execution_end")
                    obs = Observation.from_tool_result(tool_call.id, tool_call.name, exec_result)
                    observations.append(obs)
                    tool_result_messages.append(
                        ToolResultMessage(
                            tool_call_id=tool_id,
                            tool_name=tool_name,
                            result=obs.content if obs.ok else None,
                            error=None if obs.ok else obs.error,
                            artifacts=tuple(obs.artifacts),
                        )
                    )
                    trace.mark("observation_returned")

                messages.extend(tool_result_messages)

            else:
                # No tool calls — final answer
                append_message(
                    AssistantMessage(
                        content=response_text,
                    )
                )
                if on_turn_complete is not None:
                    on_turn_complete(user_goal, str(response_text) if response_text else "")
                if self._memory_callback is not None:
                    try:
                        self._memory_callback(user_goal, str(response_text) if response_text else "")
                    except Exception:
                        pass  # Memory persistence failures are non-fatal
                return AgentLoopResult(
                    ok=True,
                    final_answer=str(response_text) if response_text else None,
                    steps=steps,
                    reason="",
                    latency_ms=trace.to_dict(),
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
                        append_message(UserMessage(text))

            if self.budget.turn_count >= self.budget.max_turns:
                return AgentLoopResult(
                    ok=False,
                    final_answer=str(response_text) if response_text else None,
                    steps=steps,
                    reason=f"Max turns ({self.budget.max_turns}) reached",
                )

            # Append observations back to messages for the next model turn
            for obs in observations:
                append_message(
                    AssistantToolCallMessage(
                        content=None,
                        tool_calls=tuple(
                            ToolCall(
                                id=obs.tool_call_id or "",
                                name=obs.tool_name or "",
                                arguments={},
                            )
                        ),
                    )
                )

    async def _call_provider(
        self, messages: list[ConversationMessage], user_goal: str
    ) -> ChatResponse:
        if self.provider is None:
            raise RuntimeError(t("error.no_provider_configured"))

        # ── memory context injection ─────────────────────────────────
        memory_context = ""
        if self._memory_callback is not None:
            try:
                memory_context = self._memory_callback(user_goal)
            except Exception:
                pass  # Memory retrieval failures are non-fatal

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

        # If we have memory context, inject it as a system message at the front
        effective_messages: list[ConversationMessage]
        if memory_context:
            effective_messages = [UserMessage(memory_context)] + list(messages)
        else:
            effective_messages = list(messages)

        req = ChatRequest(model=self.model, messages=tuple(effective_messages), tools=tools)
        response = await self.provider.chat(req)
        if not (hasattr(response, "text") and hasattr(response, "tool_calls") and hasattr(response, "provider_id") and hasattr(response, "model_id")):
            raise TypeError("provider.chat() must return an object with text, tool_calls, provider_id, model_id attributes")
        return response

    async def _execute_tool(
        self, tool_call_id: str, tool_name: str, args: dict, goal: str
    ) -> Any:
        executor = self.tool_executor
        if executor is None:
            try:
                from mark.safety import SafetyPolicy
                from mark.tools import ToolExecutor
                from mark.tools.builtin import build_builtin_registry

                executor = ToolExecutor(build_builtin_registry(), SafetyPolicy())
            except Exception:
                raise RuntimeError(t("error.no_tool_executor"))

        if hasattr(executor, "execute_async"):
            from mark.safety import UntrustedSource

            res = await executor.execute_async(
                tool_name,
                args,
                source=UntrustedSource.USER,
                intent=goal,
                cancel_event=self.cancel_event,
                tool_call_id=tool_call_id,
            )
        elif hasattr(executor, "execute"):
            from mark.safety import UntrustedSource

            res = await asyncio.to_thread(
                executor.execute,
                tool_name,
                args,
                source=UntrustedSource.USER,
                intent=goal,
                cancel_event=self.cancel_event,
                tool_call_id=tool_call_id,
            )
        elif callable(executor):
            res = executor(tool_name, args)
        else:
            raise RuntimeError(t("error.unsupported_tool_executor", type=type(executor).__name__))

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
