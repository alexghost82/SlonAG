"""Iterative Multi-Turn Agent Loop Runtime (Wave 15)."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent.observation import Observation, ObservationKind
from agent.steering import SteeringKind, SteeringQueue, SteeringSignal
from mark.tools.contracts import ToolResult
from providers.contracts import ChatMessage, ChatRequest, ChatResponse, ModelInfo, ToolCall


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


class AgentLoop:
    """Core multi-turn model -> tool -> observation -> model orchestration engine."""

    def __init__(
        self,
        provider: Any = None,
        tool_executor: Any = None,
        budget: LoopBudget | None = None,
        loop_detector: LoopDetector | None = None,
    ) -> None:
        self.provider = provider
        self.tool_executor = tool_executor
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
        messages: list[ChatMessage] = [ChatMessage(role="user", content=user_goal)]

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
                        messages.append(ChatMessage(role="user", content=text))

            self.budget.turn_count += 1

            # Dispatch call to model provider
            response = await self._call_provider(messages)

            response_text = getattr(response, "text", None)
            if response_text is None and isinstance(response, dict):
                response_text = response.get("text", "")
            elif response_text is None and isinstance(response, str):
                response_text = response

            tool_calls = getattr(response, "tool_calls", ()) or ()
            if isinstance(response, dict) and not tool_calls:
                tool_calls = response.get("tool_calls", ())

            if response_text:
                messages.append(ChatMessage(role="assistant", content=str(response_text)))

            if not tool_calls:
                return AgentLoopResult(
                    ok=True,
                    final_answer=str(response_text) if response_text else None,
                    steps=steps,
                    reason="Completed successfully",
                )

            for tool_call in tool_calls:
                self.budget.tool_call_count += 1
                exceeded, reason = self.budget.is_exceeded()
                if exceeded:
                    return AgentLoopResult(
                        ok=False,
                        final_answer=str(response_text) if response_text else None,
                        steps=steps,
                        reason=reason or "Budget exceeded",
                    )

                tool_id, tool_name, tool_args = self._parse_tool_call(tool_call)

                # Execute tool, returning observation on error instead of crashing
                try:
                    raw_res = await self._execute_tool(tool_name, tool_args, user_goal)
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
                except Exception as exc:
                    obs = Observation(
                        tool_call_id=tool_id,
                        tool_name=tool_name,
                        kind=ObservationKind.TOOL_ERROR,
                        ok=False,
                        error=str(exc),
                    )

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
                if is_loop:
                    return AgentLoopResult(
                        ok=False,
                        final_answer=None,
                        steps=steps,
                        reason=loop_reason or "Loop detected",
                    )

                obs_payload = (
                    obs.to_model_dict()
                    if hasattr(obs, "to_model_dict")
                    else str(obs)
                )
                messages.append(
                    ChatMessage(
                        role="user",
                        content=f"Observation [{tool_name}]: {json.dumps(obs_payload, default=str)}",
                    )
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
                        messages.append(ChatMessage(role="user", content=text))

    async def _call_provider(self, messages: list[ChatMessage]) -> Any:
        if self.provider is None:
            return ChatResponse(
                text="No provider configured", provider_id="none", model_id="none"
            )

        if hasattr(self.provider, "chat"):
            chat_fn = self.provider.chat
            model = ModelInfo(
                provider_id="default",
                model_id="default",
                display_name="default",
                text=True,
                tool_calling=True,
            )
            req = ChatRequest(model=model, messages=messages)
            try:
                res = chat_fn(req)
            except TypeError:
                res = chat_fn(messages)
        elif callable(self.provider):
            res = self.provider(messages)
        else:
            raise RuntimeError(f"Unsupported provider type: {type(self.provider)}")

        if inspect.isawaitable(res):
            res = await res

        return res

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
            exec_fn = executor.execute
            try:
                from mark.safety import UntrustedSource

                res = exec_fn(
                    tool_name, args, source=UntrustedSource.USER, intent=goal
                )
            except TypeError:
                res = exec_fn(tool_name, args)
        elif callable(executor):
            res = executor(tool_name, args)
        else:
            raise RuntimeError(f"Unsupported tool_executor type: {type(executor)}")

        if inspect.isawaitable(res):
            res = await res

        return res

    @staticmethod
    def _parse_tool_call(tool_call: Any) -> tuple[str, str, dict]:
        if isinstance(tool_call, ToolCall):
            return (
                tool_call.id or "call_0",
                tool_call.name,
                dict(tool_call.arguments),
            )
        if isinstance(tool_call, dict):
            tc_id = tool_call.get("id") or tool_call.get("tool_call_id") or "call_0"
            tc_name = tool_call.get("name") or tool_call.get("tool_name") or ""
            tc_args = tool_call.get("arguments") or tool_call.get("args") or {}
            return tc_id, tc_name, dict(tc_args)
        tc_id = getattr(tool_call, "id", "call_0")
        tc_name = getattr(tool_call, "name", "")
        tc_args = getattr(tool_call, "arguments", getattr(tool_call, "args", {}))
        return (
            tc_id,
            tc_name,
            dict(tc_args) if isinstance(tc_args, (dict, Mapping)) else {},
        )
