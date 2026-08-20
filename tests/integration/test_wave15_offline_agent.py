"""Integration tests for Wave 15 offline multi-turn AgentLoop runtime (W15-T05)."""

import asyncio
import time
from unittest.mock import MagicMock
import pytest

from agent.executor import AgentExecutor, execute_agent_loop, execute_plan
from agent.observation import Observation, ObservationKind
from agent.runtime import AgentLoop, AgentLoopResult, LoopBudget
from agent.steering import SteeringKind, SteeringQueue, SteeringSignal
from mark.safety import SafetyPolicy, UntrustedSource
from mark.tools.builtin import build_builtin_registry
from mark.tools.contracts import ToolResult
from mark.tools.executor import ToolExecutor
from providers.contracts import ChatMessage, ChatRequest, ChatResponse, ModelInfo, ToolCall


OFFLINE_MODEL = ModelInfo(
    provider_id="offline_provider",
    model_id="test_model",
    display_name="Offline test model",
    text=True,
    tool_calling=True,
)


@pytest.mark.asyncio
async def test_offline_agent_multi_turn_tool_execution(tmp_path):
    """Verify multi-turn tool execution across multiple turns without network calls."""
    test_file = tmp_path / "data.txt"
    test_file.write_text("Secret content 123", encoding="utf-8")

    responses = [
        ChatResponse(
            text="I will read the file first.",
            provider_id="offline_provider",
            model_id="test_model",
            tool_calls=(
                ToolCall(
                    id="call_read_1",
                    name="read_file",
                    arguments={"path": str(test_file)},
                ),
            ),
        ),
        ChatResponse(
            text="File read successfully. Now summarizing.",
            provider_id="offline_provider",
            model_id="test_model",
            tool_calls=(),
        ),
    ]

    recorded_requests = []

    async def mock_chat(req: ChatRequest) -> ChatResponse:
        recorded_requests.append(req)
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    registry = build_builtin_registry()
    tool_executor = ToolExecutor(registry, SafetyPolicy())

    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal=f"Read and summarize {test_file}",
        provider=mock_provider,
        tool_executor=tool_executor,
    )

    assert result.ok is True
    assert result.final_answer == "File read successfully. Now summarizing."
    assert len(result.steps) == 1
    assert result.steps[0].tool_name == "read_file"
    assert result.steps[0].observation.ok is True
    assert "Secret content 123" in str(result.steps[0].observation.content)
    assert len(recorded_requests) == 2


@pytest.mark.asyncio
async def test_offline_agent_tool_error_self_correction():
    """Verify that tool errors are returned as observations allowing self-correction."""
    responses = [
        ChatResponse(
            text="Trying first attempt with bad arguments.",
            provider_id="offline_provider",
            model_id="test_model",
            tool_calls=(
                ToolCall(
                    id="call_fail",
                    name="read_file",
                    arguments={"path": "/nonexistent/file/path.txt"},
                ),
            ),
        ),
        ChatResponse(
            text="First attempt failed. Trying fallback path.",
            provider_id="offline_provider",
            model_id="test_model",
            tool_calls=(
                ToolCall(
                    id="call_succ",
                    name="read_file",
                    arguments={"path": "/valid/fallback.txt"},
                ),
            ),
        ),
        ChatResponse(
            text="Recovered from error successfully.",
            provider_id="offline_provider",
            model_id="test_model",
            tool_calls=(),
        ),
    ]

    async def mock_chat(req: ChatRequest) -> ChatResponse:
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    def mock_tool_executor(tool_name: str, args: dict):
        path = args.get("path", "")
        if "nonexistent" in path:
            raise FileNotFoundError(f"File not found: {path}")
        return ToolResult(ok=True, code="ok", message="Fallback content read.")

    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal="Read configuration file",
        provider=mock_provider,
        tool_executor=mock_tool_executor,
    )

    assert result.ok is True
    assert result.final_answer == "Recovered from error successfully."
    assert len(result.steps) == 2

    # Step 1: Failed observation recorded without crashing loop
    assert result.steps[0].tool_name == "read_file"
    assert result.steps[0].observation.ok is False
    assert result.steps[0].observation.kind == ObservationKind.TOOL_ERROR
    assert "nonexistent" in result.steps[0].observation.error

    # Step 2: Self-corrected tool execution succeeded
    assert result.steps[1].tool_name == "read_file"
    assert result.steps[1].observation.ok is True
    assert result.steps[1].observation.content == "Fallback content read."


@pytest.mark.asyncio
async def test_offline_agent_steering_interruption_cancel():
    """Verify system cancel steering signal halts AgentLoop cleanly."""
    steering_q = SteeringQueue()
    steering_q.push(
        SteeringSignal(kind=SteeringKind.SYSTEM_CANCEL, text="User emergency stop")
    )

    mock_provider = MagicMock()

    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal="Perform long autonomous operation",
        provider=mock_provider,
        steering_queue=steering_q,
    )

    assert result.ok is False
    assert "cancelled by steering signal" in result.reason.lower()
    assert len(result.steps) == 1
    assert result.steps[0].steering.kind == SteeringKind.SYSTEM_CANCEL
    assert result.steps[0].steering.text == "User emergency stop"
    # Provider should not be invoked when cancelled at start
    assert mock_provider.chat.call_count == 0


@pytest.mark.asyncio
async def test_offline_agent_steering_guidance_injection():
    """Verify user guidance steering signal injects context into chat history."""
    responses = [
        ChatResponse(
            text="Initial step",
            provider_id="offline",
            model_id="test",
            tool_calls=(ToolCall(id="c1", name="step_1", arguments={}),),
        ),
        ChatResponse(
            text="Final answer following guidance",
            provider_id="offline",
            model_id="test",
            tool_calls=(),
        ),
    ]

    recorded_messages = []

    async def mock_chat(req: ChatRequest) -> ChatResponse:
        recorded_messages.append(list(req.messages))
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    steering_q = SteeringQueue()
    steering_q.push(
        SteeringSignal(
            kind=SteeringKind.USER_GUIDANCE,
            text="Please format response as JSON",
        )
    )

    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal="Process data",
        provider=mock_provider,
        tool_executor=lambda name, args: "done",
        steering_queue=steering_q,
    )

    assert result.ok is True
    assert result.final_answer == "Final answer following guidance"
    # Check that guidance message was injected into prompt context
    first_req_msgs = recorded_messages[0]
    guidance_found = any(
        "Please format response as JSON" in m.content for m in first_req_msgs
    )
    assert guidance_found is True


@pytest.mark.asyncio
async def test_offline_agent_budget_enforcement_turns():
    """Verify budget max turns limit halts execution."""
    mock_provider = MagicMock()
    mock_provider.chat.return_value = ChatResponse(
        text="Looping...",
        provider_id="offline",
        model_id="test",
        tool_calls=(ToolCall(id="c", name="dummy_tool", arguments={}),),
    )

    budget = LoopBudget(max_turns=3)
    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal="Infinite loop goal",
        provider=mock_provider,
        tool_executor=lambda name, args: "ok",
        budget=budget,
    )

    assert result.ok is False
    assert "max turns (3) reached" in result.reason.lower()


@pytest.mark.asyncio
async def test_offline_agent_budget_enforcement_tool_calls():
    """Verify budget max tool calls limit halts execution."""
    mock_provider = MagicMock()
    mock_provider.chat.return_value = ChatResponse(
        text="Executing multiple tools",
        provider_id="offline",
        model_id="test",
        tool_calls=(
            ToolCall(id="c1", name="t1", arguments={}),
            ToolCall(id="c2", name="t2", arguments={}),
            ToolCall(id="c3", name="t3", arguments={}),
        ),
    )

    budget = LoopBudget(max_tool_calls=2)
    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal="Multi-tool call goal",
        provider=mock_provider,
        tool_executor=lambda name, args: "ok",
        budget=budget,
    )

    assert result.ok is False
    assert "max tool calls (2) reached" in result.reason.lower()


@pytest.mark.asyncio
async def test_offline_agent_budget_enforcement_timeout():
    """Verify timeout limit halts execution."""
    mock_provider = MagicMock()
    mock_provider.chat.return_value = ChatResponse(
        text="Slow task",
        provider_id="offline",
        model_id="test",
        tool_calls=(ToolCall(id="c1", name="t1", arguments={}),),
    )

    budget = LoopBudget(timeout_seconds=0.05)
    time.sleep(0.06)

    result = await execute_agent_loop(
        model=OFFLINE_MODEL,
        user_goal="Timeout goal",
        provider=mock_provider,
        tool_executor=lambda name, args: "ok",
        budget=budget,
    )

    assert result.ok is False
    assert "timeout" in result.reason.lower()


def test_offline_agent_legacy_execute_plan_intact(monkeypatch: pytest.MonkeyPatch):
    """Verify legacy execute_plan and AgentExecutor work offline."""
    import agent.planner as planner_mod

    def mock_create_plan(goal: str, context: str = "", registry=None):
        return {
            "goal": goal,
            "steps": [
                {
                    "step": 1,
                    "tool": "web_search",
                    "description": f"Search for {goal}",
                    "parameters": {"query": goal},
                    "critical": True,
                }
            ],
        }

    monkeypatch.setattr(planner_mod, "create_plan", mock_create_plan)

    def mock_call_tool(self, tool: str, params: dict, speak=None, *, intent=""):
        return "Search result output"

    monkeypatch.setattr(AgentExecutor, "_call_tool", mock_call_tool)
    monkeypatch.setattr(
        AgentExecutor, "_summarize", lambda self, g, steps, speak: "Plan executed successfully."
    )

    res = execute_plan("Legacy offline task")
    assert res == "Plan executed successfully."
