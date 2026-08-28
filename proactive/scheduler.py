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
