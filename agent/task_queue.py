from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from runtime.jobs import Job, JobEngine, JobState

AGENT_TASK_TYPE = "agent_task"
DEFAULT_MAX_QUEUE_DEPTH = 256
_DEFAULT_JOBS_PATH = Path("memory") / "slon_jobs.sqlite3"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    LOW = 3
    NORMAL = 2
    HIGH = 1


@dataclass(order=True)
class Task:
    priority: int
    created_at: float = field(compare=False)
    task_id: str = field(compare=False)
    goal: str = field(compare=False)
    status: TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result: Any = field(compare=False, default=None)
    error: str = field(compare=False, default="")
    speak: Any = field(compare=False, default=None)
    on_complete: Any = field(compare=False, default=None)
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)
    job_id: str = field(compare=False, default="")


class TaskQueue:
    """In-memory index over the canonical ``JobEngine`` store.

    Production durability lives in SQLite WAL. The RAM list is only an API
    index for ``get_status()`` / callbacks and is not the source of truth.
    """

    def __init__(
        self,
        max_concurrent: int = 1,
        *,
        loop_factory: Callable[..., Any] | None = None,
        job_engine: JobEngine | None = None,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    ):
        self._lock: threading.Lock = threading.Lock()
        self._condition: threading.Condition = threading.Condition(self._lock)
        self._tasks: dict[str, Task] = {}
        self._running: bool = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count = 0
        self._loop_factory = loop_factory
        self._job_engine = job_engine
        self._max_queue_depth = max(1, int(max_queue_depth))

    def set_loop_factory(self, factory: Callable[..., Any] | None) -> None:
        self._loop_factory = factory

    def set_job_engine(self, engine: JobEngine) -> None:
        self._job_engine = engine

    def _engine(self) -> JobEngine:
        if self._job_engine is None:
            path = Path.cwd() / _DEFAULT_JOBS_PATH
            self._job_engine = JobEngine(path)
            self._job_engine.recover_running()
        return self._job_engine

    def _create_agent_loop(self, cancel_event: threading.Event):
        if self._loop_factory is not None:
            return self._loop_factory(cancel_event=cancel_event)
        from agent.executor import create_queued_agent_loop

        return create_queued_agent_loop(cancel_event=cancel_event)

    def start(self) -> None:
        if self._running:
            return
        self._engine().recover_running()
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AgentTaskQueue",
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()

    def _inflight_count(self) -> int:
        engine = self._engine()
        return (
            len(engine.list_by_state(JobState.PENDING, job_type=AGENT_TASK_TYPE))
            + len(engine.list_by_state(JobState.RUNNING, job_type=AGENT_TASK_TYPE))
            + len(engine.list_by_state(JobState.RETRYING, job_type=AGENT_TASK_TYPE))
        )

    def submit(
        self,
        goal: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        speak: Callable | None = None,
        on_complete: Callable | None = None,
    ) -> str:
        engine = self._engine()
        if self._inflight_count() >= self._max_queue_depth:
            raise RuntimeError("task queue is full")

        task_id = str(uuid.uuid4())[:8]
        job = engine.enqueue(
            type=AGENT_TASK_TYPE,
            payload={
                "goal": goal,
                "task_id": task_id,
                "priority": priority.value,
            },
            idempotency_key=f"{AGENT_TASK_TYPE}:{task_id}",
        )
        task = Task(
            priority=priority.value,
            created_at=time.time(),
            task_id=task_id,
            goal=goal,
            speak=speak,
            on_complete=on_complete,
            job_id=job.job_id,
        )
        with self._condition:
            self._tasks[task_id] = task
            self._condition.notify()
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False
            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            job_id = task.job_id
        if job_id:
            try:
                self._engine().cancel(job_id, reason="user")
            except KeyError:
                pass
        return True

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "goal": task.goal,
                "status": task.status.value,
                "result": task.result,
                "error": task.error,
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal": t.goal[:50],
                    "status": t.status.value,
                }
                for t in self._tasks.values()
            ]

    def pending_count(self) -> int:
        return len(self._engine().list_by_state(JobState.PENDING, job_type=AGENT_TASK_TYPE))

    def _task_from_job(self, job: Job) -> Task:
        payload = job.payload if isinstance(job.payload, dict) else {}
        task_id = str(payload.get("task_id") or job.job_id[:8])
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing is not None:
                existing.job_id = job.job_id
                existing.status = TaskStatus.RUNNING
                return existing
            task = Task(
                priority=int(payload.get("priority", TaskPriority.NORMAL.value)),
                created_at=time.time(),
                task_id=task_id,
                goal=str(payload.get("goal") or ""),
                status=TaskStatus.RUNNING,
                job_id=job.job_id,
            )
            self._tasks[task_id] = task
            return task

    def _worker_loop(self) -> None:
        engine = self._engine()
        while self._running:
            with self._condition:
                while self._running and self._active_count >= self._max_concurrent:
                    self._condition.wait(timeout=1.0)
                if not self._running:
                    return
            job = engine.claim(job_type=AGENT_TASK_TYPE)
            if job is None:
                with self._condition:
                    self._condition.wait(timeout=0.5)
                continue
            task = self._task_from_job(job)
            with self._lock:
                self._active_count += 1
                task.status = TaskStatus.RUNNING
            threading.Thread(
                target=self._run_task,
                args=(task,),
                daemon=True,
                name=f"AgentTask-{task.task_id}",
            ).start()

    def _run_task(self, task: Task) -> None:
        engine = self._engine()
        try:
            if task.job_id and engine.get(task.job_id) is not None:
                claimed = engine.get(task.job_id)
                if claimed is not None and claimed.state in (
                    JobState.PENDING,
                    JobState.RETRYING,
                ):
                    engine.claim_job(task.job_id)
            agent_loop = self._create_agent_loop(task.cancel_flag)
            result = asyncio.run(agent_loop.run(user_goal=task.goal))
            text = getattr(result, "final_answer", None) or getattr(result, "reason", "") or ""

            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                    terminal = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = text
                    terminal = TaskStatus.COMPLETED
                self._active_count = max(0, self._active_count - 1)

            if task.job_id:
                if terminal is TaskStatus.CANCELLED:
                    engine.cancel(task.job_id, reason="user")
                else:
                    engine.complete(task.job_id, result_ref=text[:200] if text else None)

            if task.speak and text and not task.cancel_flag.is_set():
                try:
                    task.speak(text)
                except Exception:
                    pass

            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, text)
                except Exception:
                    pass

        except Exception as exc:
            with self._lock:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                self._active_count = max(0, self._active_count - 1)
            if task.job_id:
                try:
                    engine.fail(task.job_id, str(exc), retry=False)
                except KeyError:
                    pass

        with self._condition:
            self._condition.notify()


_queue = TaskQueue()
_queue_started = False
_queue_lock = threading.Lock()


def configure_shared_engine(engine: JobEngine) -> None:
    """Point the process-global queue at the stack JobEngine (one sqlite store)."""
    with _queue_lock:
        _queue.set_job_engine(engine)


def get_queue() -> TaskQueue:
    global _queue_started
    with _queue_lock:
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue
