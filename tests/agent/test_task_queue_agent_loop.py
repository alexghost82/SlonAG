"""TaskQueue must create AgentLoop, never AgentExecutor."""

from __future__ import annotations

import threading

from agent.runtime import AgentLoopResult
from agent.task_queue import TaskQueue, TaskStatus


def test_run_task_uses_injected_agent_loop_factory() -> None:
    created = {"count": 0}

    class FakeLoop:
        async def run(self, user_goal: str, **_kwargs: object) -> AgentLoopResult:
            created["goal"] = user_goal
            return AgentLoopResult(ok=True, final_answer="from-loop")

    def factory(*, cancel_event: threading.Event) -> FakeLoop:
        created["count"] += 1
        created["cancel"] = cancel_event
        return FakeLoop()

    queue = TaskQueue(loop_factory=factory)
    task_id = queue.submit("do the thing")
    # Drive the worker path directly to keep the test deterministic.
    task = queue._tasks[task_id]
    queue._run_task(task)
    assert created["count"] == 1
    assert created["goal"] == "do the thing"
    assert task.status is TaskStatus.COMPLETED
    assert task.result == "from-loop"


def test_execute_plan_delegates_to_agent_loop(monkeypatch) -> None:
    from agent import executor as executor_mod

    class FakeLoop:
        async def run(self, user_goal: str, **_kwargs: object) -> AgentLoopResult:
            return AgentLoopResult(ok=True, final_answer=f"loop:{user_goal}")

    monkeypatch.setattr(
        executor_mod,
        "create_queued_agent_loop",
        lambda **_kwargs: FakeLoop(),
    )
    assert executor_mod.execute_plan("hello") == "loop:hello"


