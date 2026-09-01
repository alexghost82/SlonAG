"""Proactive scheduler for E2E tests."""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class ScheduledTask:
    name: str
    schedule: str  # e.g. "every_5s", "on_idle"
    handler: Callable
    active: bool = True

class ProactiveScheduler:
    """Schedules proactive agent tasks."""
    def __init__(self) -> None:
        self.tasks: list[ScheduledTask] = []
        self._callbacks: list[Callable] = []

    def schedule(self, name: str, schedule: str, handler: Callable) -> ScheduledTask:
        task = ScheduledTask(name=name, schedule=schedule, handler=handler, active=True)
        self.tasks.append(task)
        return task

    def on_tick(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def tick(self) -> list[dict]:
        results = []
        for cb in self._callbacks:
            results.append(cb())
        return results

    def list_tasks(self) -> list[ScheduledTask]:
        return list(self.tasks)

# E2E compatibility: schedule_once, start, stop

class ProactiveScheduler:
    """Full proactive scheduler with asyncio support."""
    def __init__(self) -> None:
        self.tasks: list[ScheduledTask] = []
        self._callbacks: list[Callable] = []
        self._running = False
        self._events: list[dict[str, Any]] = []

    def schedule_once(
        self,
        topic: str,
        payload: dict[str, Any] | None = None,
        delay_seconds: float = 0.0,
    ) -> str:
        """Schedule a task to fire once after delay_seconds. Returns task_id."""
        import uuid
        task_id = uuid.uuid4().hex[:12]

        async def _fire() -> None:
            await asyncio.sleep(delay_seconds)
            self._events.append({
                "task_id": task_id,
                "topic": topic,
                "payload": payload or {},
                "fired_at": time.monotonic(),
            })

        if not self._running:
            # Auto-start
            self._running = True
            asyncio.create_task(_fire())
        else:
            asyncio.create_task(_fire())
        return task_id

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._events.clear()

    def list_tasks(self) -> list[ScheduledTask]:
        return list(self.tasks)

    def list_events(self) -> list[dict[str, Any]]:
        return list(self._events)
