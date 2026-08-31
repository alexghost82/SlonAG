"""Unit tests for POST /v1/chat route handler."""

from __future__ import annotations

from server.routes._common import DevicePrincipal
from server.routes.chat import ChatHandler, ChatHandlerWithRuntime
from server.schemas import CODE_APPROVAL_REQUIRED, CODE_MISSING_FIELD, CODE_UNAUTHORIZED


def test_chat_unauthenticated_returns_401() -> None:
    handler = ChatHandler()
    response = handler.post(
        principal=None,
        body={"message": "hi", "idempotency_key": "c1"},
    )
    assert response.status_code == 401


def test_chat_requires_idempotency_key() -> None:
    handler = ChatHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.post(principal=principal, body={"message": "hi"})
    assert response.status_code == 400
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_MISSING_FIELD


def test_chat_idempotency_no_double_side_effect() -> None:
    handler = ChatHandler()
    principal = DevicePrincipal(device_id="dev_ok")
    body = {
        "message": "hello",
        "idempotency_key": "chat-1",
        "api_key": "sk-should-never-echo",
    }
    first = handler.post(principal=principal, body=body)
    second = handler.post(principal=principal, body=body)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.body == second.body
    assert first.body.get("approval_required") is True
    assert first.body.get("status") == CODE_APPROVAL_REQUIRED
    assert handler.idempotency.side_effect_count("chat:chat-1") == 1
    assert "api_key" not in first.body
    assert "sk-should-never-echo" not in str(first.body)


# --- ChatHandlerWithRuntime tests -------------------------------------------


class _MockObservation:
    """Minimal stand-in for agent.observation.Observation."""

    def __init__(
        self,
        ok: bool = True,
        kind_str: str = "success",
        content: str | None = None,
        error: str | None = None,
    ) -> None:
        from agent.observation import ObservationKind
        self.ok = ok
        self.kind = ObservationKind(kind_str)
        self.content = content
        self.error = error


class _MockStep:
    """Minimal stand-in for agent.runtime.AgentLoopStepResult."""

    def __init__(
        self,
        turn_index: int = 0,
        tool_name: str | None = None,
        observation=None,
        steering=None,
    ) -> None:
        self.turn_index = turn_index
        self.tool_name = tool_name
        self.observation = observation
        self.steering = steering


class _MockAgentLoopResult:
    """Minimal stand-in for agent.runtime.AgentLoopResult."""

    def __init__(
        self,
        ok: bool = True,
        final_answer: str = "Ответ агента",
        reason: str = "Completed successfully",
        steps: list | None = None,
    ) -> None:
        self.ok = ok
        self.final_answer = final_answer
        self.reason = reason
        self.steps = steps or []


class _MockAgentLoop:
    """Minimal stand-in for agent.runtime.AgentLoop."""

    def __init__(self, result: _MockAgentLoopResult | None = None) -> None:
        self._result = result or _MockAgentLoopResult()

    async def run(self, user_goal: str, history=()) -> _MockAgentLoopResult:
        return self._result


class _MockRuntimeStack:
    """Fake runtime stack exposing an agent_loop."""

    def __init__(self, agent_loop: _MockAgentLoop | None = None) -> None:
        self.agent_loop = agent_loop


def test_handler_with_runtime_degrades_without_stack() -> None:
    handler = ChatHandlerWithRuntime()
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.post(
        principal=principal,
        body={"message": "hello", "idempotency_key": "w1"},
    )
    assert response.status_code == 202
    assert response.body.get("event") == "approval_required"
    assert response.body.get("approval_required") is True


def test_handler_with_runtime_degrades_without_agent_loop() -> None:
    stack = _MockRuntimeStack(agent_loop=None)
    handler = ChatHandlerWithRuntime(runtime_stack=stack)
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.post(
        principal=principal,
        body={"message": "hello", "idempotency_key": "w2"},
    )
    assert response.status_code == 202
    assert response.body.get("event") == "approval_required"


def test_handler_with_runtime_success() -> None:
    result = _MockAgentLoopResult(ok=True, final_answer="Ответ агента")
    mock_loop = _MockAgentLoop(result)
    stack = _MockRuntimeStack(agent_loop=mock_loop)
    handler = ChatHandlerWithRuntime(runtime_stack=stack)
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.post(
        principal=principal,
        body={"message": "what is 2+2?", "idempotency_key": "w3"},
    )
    assert response.status_code == 200
    assert response.body.get("event") == "agent_response"
    assert response.body.get("answer") == "Ответ агента"
    assert response.body.get("ok") is True


def test_handler_with_runtime_error_message_in_russian() -> None:
    obs = _MockObservation(
        ok=False,
        kind_str="tool_error",
        content=None,
        error="disk full",
    )
    step = _MockStep(turn_index=0, tool_name="shell_exec", observation=obs)
    result = _MockAgentLoopResult(
        ok=False,
        final_answer=None,
        reason="Max turns reached",
        steps=[step],
    )
    mock_loop = _MockAgentLoop(result)
    stack = _MockRuntimeStack(agent_loop=mock_loop)
    handler = ChatHandlerWithRuntime(runtime_stack=stack)
    principal = DevicePrincipal(device_id="dev_ok")
    response = handler.post(
        principal=principal,
        body={"message": "run a test", "idempotency_key": "w4"},
    )
    assert response.status_code == 200
    observations = response.body.get("observations")
    assert observations is not None
    assert any("Ошибка инструмента" in o for o in observations)


def test_handler_with_runtime_idempotency() -> None:
    result = _MockAgentLoopResult(ok=True, final_answer="answer")
    mock_loop = _MockAgentLoop(result)
    stack = _MockRuntimeStack(agent_loop=mock_loop)
    handler = ChatHandlerWithRuntime(runtime_stack=stack)
    principal = DevicePrincipal(device_id="dev_ok")
    first = handler.post(
        principal=principal,
        body={"message": "hi", "idempotency_key": "idem-chat", "api_key": "sk-secret"},
    )
    second = handler.post(
        principal=principal,
        body={"message": "hi", "idempotency_key": "idem-chat", "api_key": "sk-secret2"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.body == second.body
    assert handler.idempotency.side_effect_count("chat:idem-chat") == 1
    assert "sk-secret" not in str(first.body)
    assert "sk-secret2" not in str(first.body)


def test_handler_with_runtime_unauthenticated_returns_401() -> None:
    stack = _MockRuntimeStack(agent_loop=_MockAgentLoop())
    handler = ChatHandlerWithRuntime(runtime_stack=stack)
    response = handler.post(principal=None, body={"message": "hi", "idempotency_key": "w5"})
    assert response.status_code == 401
