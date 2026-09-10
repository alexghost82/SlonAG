"""TaskQueue must create AgentLoop, never AgentExecutor."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent.runtime import AgentLoopResult
from agent.task_queue import TaskQueue, TaskStatus
from runtime.jobs import JobEngine, JobState


def test_run_task_uses_injected_agent_loop_factory(tmp_path: Path) -> None:
    created = {"count": 0}

    class FakeLoop:
        async def run(self, user_goal: str, **_kwargs: object) -> AgentLoopResult:
            created["goal"] = user_goal  # type: ignore[assignment]
            return AgentLoopResult(ok=True, final_answer="from-loop")

    def factory(*, cancel_event: threading.Event) -> FakeLoop:
        created["count"] += 1
        created["cancel"] = cancel_event  # type: ignore[assignment]
        return FakeLoop()

    engine = JobEngine(tmp_path / "jobs.sqlite3")
    queue = TaskQueue(loop_factory=factory, job_engine=engine)
    task_id = queue.submit("do the thing")
    # Drive the worker path directly to keep the test deterministic.
    task = queue._tasks[task_id]
    queue._run_task(task)
    assert created["count"] == 1
    assert created["goal"] == "do the thing"
    assert task.status is TaskStatus.COMPLETED
    assert task.result == "from-loop"
    stored = engine.get(task.job_id)
    assert stored is not None
    assert stored.state == JobState.COMPLETED
    engine.close()


def test_submit_rejects_when_queue_is_full(tmp_path: Path) -> None:
    engine = JobEngine(tmp_path / "jobs.sqlite3")
    queue = TaskQueue(job_engine=engine, max_queue_depth=2)
    queue.submit("a")
    queue.submit("b")
    with pytest.raises(RuntimeError, match="full"):
        queue.submit("c")
    engine.close()


def test_completed_task_not_reexecuted_after_engine_reopen(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"

    class FakeLoop:
        async def run(self, user_goal: str, **_kwargs: object) -> AgentLoopResult:
            return AgentLoopResult(ok=True, final_answer="done")

    engine = JobEngine(path)
    queue = TaskQueue(loop_factory=lambda **_: FakeLoop(), job_engine=engine)
    task_id = queue.submit("goal")
    queue._run_task(queue._tasks[task_id])
    job = engine.get_by_idempotency_key(f"agent_task:{task_id}")
    assert job is not None
    assert job.state == JobState.COMPLETED
    engine.close()

    restarted = JobEngine(path)
    restarted.recover_running()
    leftover = restarted.get_by_idempotency_key(f"agent_task:{task_id}")
    assert leftover is not None
    assert leftover.state == JobState.COMPLETED
    assert restarted.claim(job_type="agent_task") is None
    restarted.close()


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
