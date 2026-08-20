"""Unit tests for agent/runtime.py."""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.observation import Observation, ObservationKind
from agent.runtime import (
    AgentLoop,
    AgentLoopResult,
    AgentLoopStepResult,
    LoopBudget,
    LoopDetector,
)
from agent.steering import SteeringKind, SteeringQueue, SteeringSignal
from mark.tools.contracts import ToolResult
from providers.contracts import (
    AssistantToolCallMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ToolCall,
    ToolResultMessage,
)


MODEL = ModelInfo(
    provider_id="test",
    model_id="test-model",
    display_name="Test model",
    text=True,
    tool_calling=True,
)


def test_agent_loop_requires_explicit_selected_model() -> None:
    with pytest.raises(TypeError, match="model"):
        AgentLoop(provider=MagicMock())  # type: ignore[call-arg]


def test_loop_budget_defaults_and_is_exceeded():
    """Verify default values and threshold detection for LoopBudget."""
    budget = LoopBudget()
    assert budget.max_tool_calls == 15
    assert budget.max_turns == 10
    assert budget.timeout_seconds == 120.0
    assert budget.tool_call_count == 0
    assert budget.turn_count == 0

    exceeded, reason = budget.is_exceeded()
    assert exceeded is False
    assert reason is None

    # Test max_tool_calls
    budget.tool_call_count = 15
    exceeded, reason = budget.is_exceeded()
    assert exceeded is True
    assert "tool calls" in reason.lower()

    # Test max_turns
    budget.tool_call_count = 0
    budget.turn_count = 10
    exceeded, reason = budget.is_exceeded()
    assert exceeded is True
    assert "turns" in reason.lower()

    # Test timeout
    budget.turn_count = 0
    budget.start_time = time.time() - 200.0
    exceeded, reason = budget.is_exceeded()
    assert exceeded is True
    assert "timeout" in reason.lower()


@pytest.mark.parametrize("limit", [0, 1, 4])
def test_loop_budget_allows_exactly_n_completed_calls(limit: int) -> None:
    budget = LoopBudget(max_tool_calls=limit)
    for completed in range(limit):
        budget.tool_call_count = completed
        assert budget.is_exceeded()[0] is False
    budget.tool_call_count = limit
    assert budget.is_exceeded()[0] is True


@pytest.mark.asyncio
async def test_native_tool_result_keeps_correlation_id() -> None:
    requests: list[ChatRequest] = []
    responses = [
        ChatResponse(
            text="",
            provider_id="test",
            model_id="test-model",
            tool_calls=(ToolCall("call-42", "read_file", {"path": "x"}),),
        ),
        ChatResponse("done", "test", "test-model"),
    ]

    async def chat(request: ChatRequest) -> ChatResponse:
        requests.append(request)
        return responses.pop(0)

    provider = MagicMock()
    provider.chat.side_effect = chat
    result = await AgentLoop(
        provider=provider,
        tool_executor=lambda _name, _args: "contents",
        model=MODEL,
    ).run("read")

    assert result.ok
    assert requests[1].messages[-2].role == "assistant"
    assert isinstance(requests[1].messages[-2], AssistantToolCallMessage)
    assert requests[1].messages[-2].tool_calls[0].id == "call-42"
    tool_result = requests[1].messages[-1]
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.role == "tool"
    assert tool_result.tool_call_id == "call-42"
    assert tool_result.name == "read_file"
    assert tool_result.result == "contents"


@pytest.mark.asyncio
async def test_provider_wait_is_actively_timed_out() -> None:
    async def chat(_request: ChatRequest) -> ChatResponse:
        await asyncio.sleep(1)
        return ChatResponse("late", "test", "test-model")

    provider = MagicMock()
    provider.chat.side_effect = chat
    result = await AgentLoop(
        provider=provider,
        model=MODEL,
        budget=LoopBudget(timeout_seconds=0.01),
    ).run("wait")

    assert result.ok is False
    assert "timeout" in result.reason.lower()


def test_loop_detector_consecutive_calls():
    """Verify detection of N>=3 consecutive identical tool calls."""
    detector = LoopDetector(max_consecutive=3)

    detector.record_call("read_file", {"path": "/tmp/a.txt"}, "content 1")
    assert detector.check_loop() == (False, None)

    detector.record_call("read_file", {"path": "/tmp/a.txt"}, "content 2")
    assert detector.check_loop() == (False, None)

    detector.record_call("read_file", {"path": "/tmp/a.txt"}, "content 3")
    is_loop, reason = detector.check_loop()
    assert is_loop is True
    assert "3 consecutive identical tool calls" in reason


def test_loop_detector_oscillating_calls():
    """Verify detection of A/B/A/B/A/B oscillating call patterns."""
    detector = LoopDetector(max_oscillating=3)

    calls = [
        ("step_a", {"x": 1}, "res1"),
        ("step_b", {"y": 2}, "res2"),
        ("step_a", {"x": 1}, "res3"),
        ("step_b", {"y": 2}, "res4"),
        ("step_a", {"x": 1}, "res5"),
    ]
    for name, args, summary in calls:
        detector.record_call(name, args, summary)
        assert detector.check_loop() == (False, None)

    detector.record_call("step_b", {"y": 2}, "res6")
    is_loop, reason = detector.check_loop()
    assert is_loop is True
    assert "oscillating call pattern" in reason.lower()


def test_loop_detector_zero_progress():
    """Verify detection of zero-progress repetition loops."""
    detector = LoopDetector(max_zero_progress=3)

    detector.record_call("fetch_url", {"url": "http://test.com"}, "404 Not Found")
    detector.record_call("other_tool", {"a": 1}, "ok")
    detector.record_call("fetch_url", {"url": "http://test.com"}, "404 Not Found")
    assert detector.check_loop() == (False, None)

    detector.record_call("fetch_url", {"url": "http://test.com"}, "404 Not Found")
    is_loop, reason = detector.check_loop()
    assert is_loop is True
    assert "zero-progress repetition loop" in reason.lower()


def test_agent_loop_dataclasses():
    """Verify AgentLoopStepResult and AgentLoopResult structure."""
    obs = Observation(
        tool_call_id="call_1",
        tool_name="test_tool",
        kind=ObservationKind.SUCCESS,
        ok=True,
        content="hello",
    )
    step = AgentLoopStepResult(turn_index=1, tool_name="test_tool", observation=obs)
    assert step.turn_index == 1
    assert step.tool_name == "test_tool"
    assert step.observation == obs
    assert step.steering is None

    result = AgentLoopResult(ok=True, final_answer="done", steps=[step], reason="ok")
    assert result.ok is True
    assert result.final_answer == "done"
    assert len(result.steps) == 1
    assert result.reason == "ok"


@pytest.mark.asyncio
async def test_agent_loop_single_turn_text_response():
    """Verify AgentLoop completes on first turn when model returns text only."""
    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=ChatResponse(
        text="Hello user!", provider_id="test", model_id="test"
    ))

    loop = AgentLoop(provider=mock_provider, model=MODEL)
    result = await loop.run("Say hello")

    assert result.ok is True
    assert result.final_answer == "Hello user!"
    assert len(result.steps) == 0
    assert result.reason == "Completed successfully"


@pytest.mark.asyncio
async def test_agent_loop_multi_turn_tool_execution():
    """Verify multi-turn tool execution and observation handling."""
    responses = [
        ChatResponse(
            text="Checking file...",
            provider_id="test",
            model_id="test",
            tool_calls=(
                ToolCall(
                    id="call_123",
                    name="read_file",
                    arguments={"path": "/tmp/test.txt"},
                ),
            ),
        ),
        ChatResponse(
            text="File contents: hello world",
            provider_id="test",
            model_id="test",
            tool_calls=(),
        ),
    ]

    async def mock_chat(req):
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    def mock_executor(tool_name, args):
        return ToolResult(ok=True, code="ok", message="File contents: hello world")

    loop = AgentLoop(provider=mock_provider, tool_executor=mock_executor, model=MODEL)
    result = await loop.run("Read file /tmp/test.txt")

    assert result.ok is True
    assert result.final_answer == "File contents: hello world"
    assert len(result.steps) == 1
    assert result.steps[0].tool_name == "read_file"
    assert result.steps[0].observation.ok is True
    assert result.steps[0].observation.content == "File contents: hello world"


@pytest.mark.asyncio
async def test_agent_loop_tool_error_self_correction():
    """Verify tool errors return observations for self-correction instead of crashing."""
    responses = [
        ChatResponse(
            text="Calling broken tool",
            provider_id="test",
            model_id="test",
            tool_calls=(
                ToolCall(id="call_err", name="bad_tool", arguments={}),
            ),
        ),
        ChatResponse(
            text="I see the error, fixing it now.",
            provider_id="test",
            model_id="test",
            tool_calls=(),
        ),
    ]

    async def mock_chat(req):
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    def mock_executor(tool_name, args):
        raise RuntimeError("Disk full")

    loop = AgentLoop(provider=mock_provider, tool_executor=mock_executor, model=MODEL)
    result = await loop.run("Run command")

    assert result.ok is True
    assert result.final_answer == "I see the error, fixing it now."
    assert len(result.steps) == 1
    assert result.steps[0].observation.ok is False
    assert result.steps[0].observation.kind == ObservationKind.TOOL_ERROR
    assert "Disk full" in result.steps[0].observation.error


@pytest.mark.asyncio
async def test_agent_loop_budget_exceeded():
    """Verify loop halts when budget turns or tool calls are exceeded."""
    responses = [
        ChatResponse(
            text="",
            provider_id="test",
            model_id="test",
            tool_calls=(
                ToolCall(id=f"c_{i}", name="loop_tool", arguments={"i": i}),
            ),
        )
        for i in range(10)
    ]

    async def mock_chat(req):
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    budget = LoopBudget(max_turns=3, max_tool_calls=15)
    loop = AgentLoop(
        model=MODEL,
        provider=mock_provider,
        tool_executor=lambda name, args: "ok",
        budget=budget,
    )

    result = await loop.run("Loop task")
    assert result.ok is False
    assert "max turns" in result.reason.lower()


@pytest.mark.asyncio
async def test_agent_loop_loop_detector_halt():
    """Verify loop halts when LoopDetector detects identical repeated calls."""
    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=ChatResponse(
        text="",
        provider_id="test",
        model_id="test",
        tool_calls=(
            ToolCall(id="call_rep", name="repeat_tool", arguments={"key": "val"}),
        ),
    ))

    detector = LoopDetector(max_consecutive=3)
    loop = AgentLoop(
        model=MODEL,
        provider=mock_provider,
        tool_executor=lambda name, args: "same output",
        loop_detector=detector,
    )

    result = await loop.run("Infinite repeat task")
    assert result.ok is False
    assert "3 consecutive identical tool calls" in result.reason


@pytest.mark.asyncio
async def test_agent_loop_steering_cancellation():
    """Verify steering queue interrupt/cancellation halts execution cleanly."""
    steering_q = SteeringQueue()
    steering_q.push(SteeringSignal(kind=SteeringKind.SYSTEM_CANCEL, text="User cancelled"))

    mock_provider = MagicMock()
    loop = AgentLoop(provider=mock_provider, model=MODEL)

    result = await loop.run("Long task", steering_queue=steering_q)

    assert result.ok is False
    assert "cancelled by steering signal" in result.reason.lower()
    assert len(result.steps) == 1
    assert result.steps[0].steering.kind == SteeringKind.SYSTEM_CANCEL
