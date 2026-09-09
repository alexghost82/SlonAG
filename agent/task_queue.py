from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


class TaskQueue:
    def __init__(
        self,
        max_concurrent: int = 1,
        *,
        loop_factory: Callable[..., Any] | None = None,
    ):
        self._queue: list[Task] = []
        self._lock: threading.Lock = threading.Lock()
        self._condition: threading.Condition = threading.Condition(self._lock)
        self._tasks: dict[str, Task] = {}
        self._running: bool = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count = 0
        self._loop_factory = loop_factory

    def set_loop_factory(self, factory: Callable[..., Any] | None) -> None:
        self._loop_factory = factory

    def _create_agent_loop(self, cancel_event: threading.Event):
        if self._loop_factory is not None:
            return self._loop_factory(cancel_event=cancel_event)
        from agent.executor import create_queued_agent_loop

        return create_queued_agent_loop(cancel_event=cancel_event)

    def start(self) -> None:
        if self._running:
            return
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

    def submit(
        self,
        goal: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        speak: Callable | None = None,
        on_complete: Callable | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            priority=priority.value,
            created_at=time.time(),
            task_id=task_id,
            goal=goal,
            speak=speak,
            on_complete=on_complete,
        )

        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
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
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def _worker_loop(self) -> None:
        while self._running:
            task = None

            with self._condition:
                while self._running and not self._next_task():
                    self._condition.wait(timeout=1.0)
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    self._active_count += 1
                    try:
                        self._queue.remove(task)
                    except ValueError:
                        pass

            if task:
                threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"AgentTask-{task.task_id}",
                ).start()

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        for task in self._queue:
            if task.status == TaskStatus.PENDING and not task.cancel_flag.is_set():
                return task
        return None

    def _run_task(self, task: Task) -> None:
        try:
            agent_loop = self._create_agent_loop(task.cancel_flag)
            result = asyncio.run(agent_loop.run(user_goal=task.goal))
            text = getattr(result, "final_answer", None) or getattr(result, "reason", "") or ""

            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = text
                self._active_count -= 1

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
                self._active_count -= 1

        with self._condition:
            self._condition.notify()


_queue = TaskQueue()
_queue_started = False
_queue_lock = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue_started
    with _queue_lock:
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue
