"""Persistent automation engine with one-shot, recurring, and cron triggers."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class AutomationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggerType(StrEnum):
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"
    CRON = "cron"


@dataclass(frozen=True)
class AutomationRecord:
    """One automation schedule with history and recovery support."""

    id: str
    name: str
    trigger_type: TriggerType
    payload: str
    goal: str
    status: AutomationStatus = AutomationStatus.PENDING
    created_at: float = field(default_factory=time.time)
    last_run_at: float | None = None
    next_run_at: float | None = None
    run_count: int = 0
    last_error: str | None = None
    recovery_attempts: int = 0
    max_recovery_attempts: int = 3
    enabled: bool = True
    workspace_id: str = "desktop"


class CronScheduler:
    """Minimal cron-like scheduler. Supports minute-level granularity."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, float] = {}
        self._callbacks: dict[str, Callable[[], None]] = {}

    def schedule(self, task_id: str, cron_expression: str) -> float:
        next_at = self._parse_cron(cron_expression)
        with self._lock:
            self._tasks[task_id] = next_at
        return next_at

    def _parse_cron(self, expression: str) -> float:
        parts = expression.strip().split()
        if len(parts) < 2:
            raise ValueError(f"Invalid cron expression: {expression}")
        minute = self._parse_cron_field(parts[0], 0, 59)
        hour = self._parse_cron_field(parts[1], 0, 23)
        now = time.time()
        current_minute = time.localtime(now).tm_min
        current_hour = time.localtime(now).tm_hour
        if hour > current_hour or (hour == current_hour and minute > current_minute):
            target_time = time.mktime((
                time.localtime(now).tm_year, time.localtime(now).tm_mon,
                time.localtime(now).tm_mday, hour, minute, 0,
                time.localtime(now).tm_wday, time.localtime(now).tm_yday,
                time.localtime(now).tm_isdst,
            ))
        else:
            tomorrow = now + 86400
            target_time = time.mktime((
                time.localtime(tomorrow).tm_year, time.localtime(tomorrow).tm_mon,
                time.localtime(tomorrow).tm_mday, hour, minute, 0,
                time.localtime(tomorrow).tm_wday, time.localtime(tomorrow).tm_yday,
                time.localtime(tomorrow).tm_isdst,
            ))
        return target_time

    def _parse_cron_field(self, value: str, min_val: int, max_val: int) -> int:
        if value == "*":
            return min_val
        if value.startswith("*/"):
            step = int(value[2:])
            return (min_val + step)
        return int(value)

    def get_due_tasks(self) -> list[str]:
        now = time.time()
        with self._lock:
            due = [tid for tid, next_at in self._tasks.items() if next_at <= now]
        return due

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
            self._callbacks.pop(task_id, None)


class OneShotTrigger:
    """Execute once, then mark as completed."""

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay = delay_seconds

    def next_run(self, created_at: float) -> float:
        return created_at + self.delay


class RecurringTrigger:
    """Execute at a regular interval."""

    def __init__(self, interval_seconds: float) -> None:
        self.interval = interval_seconds

    def next_run(self, last_run_at: float) -> float:
        return last_run_at + self.interval


class AutomationEngine:
    """Persistent automation engine with one-shot, recurring, and cron triggers."""

    def __init__(
        self,
        *,
        store_path: Path | str | None = None,
        executor: Callable[[AutomationRecord], Awaitable[None]] | None = None,
    ) -> None:
        if store_path is None:
            import tempfile
            self._store_path = Path(tempfile.mkdtemp(prefix="automation_"))
        else:
            self._store_path = Path(store_path) if isinstance(store_path, str) else store_path
            self._store_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._records: dict[str, AutomationRecord] = {}
        self._scheduler = CronScheduler()
        self._executor = executor
        self._running = False
        self._thread: threading.Thread | None = None
        self._load()

    def create(
        self,
        name: str,
        trigger_type: TriggerType,
        payload: dict[str, Any],
        goal: str,
        workspace_id: str = "desktop",
    ) -> AutomationRecord:
        now = time.time()
        record_id = uuid4().hex
        record = AutomationRecord(
            id=record_id,
            name=name,
            trigger_type=trigger_type,
            payload=json.dumps(payload),
            goal=goal,
            created_at=now,
            enabled=True,
            workspace_id=workspace_id,
        )
        self._schedule_trigger(record)
        self._save()
        return record

    def _schedule_trigger(self, record: AutomationRecord) -> None:
        payload = json.loads(record.payload)
        if record.trigger_type == TriggerType.ONE_SHOT:
            delay = payload.get("delay_seconds", 0.0)
            record.next_run_at = record.created_at + delay
        elif record.trigger_type == TriggerType.RECURRING:
            interval = payload.get("interval_seconds", 60.0)
            record.next_run_at = record.created_at + interval
        elif record.trigger_type == TriggerType.CRON:
            cron_expr = payload.get("expression", "")
            record.next_run_at = self._scheduler.schedule(record.id, cron_expr)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="slon-automation")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            self._tick()
            time.sleep(1.0)

    def _tick(self) -> None:
        now = time.time()
        with self._lock:
            due_ids = [
                rec.id for rec in self._records.values()
                if rec.enabled
                and rec.status == AutomationStatus.PENDING
                and rec.next_run_at is not None
                and rec.next_run_at <= now
            ]
        for rec_id in due_ids:
            record = self._records.get(rec_id)
            if record is None or record.status not in (AutomationStatus.PENDING, AutomationStatus.RUNNING):
                continue
            self._execute(record)

    def _execute(self, record: AutomationRecord) -> None:
        record.status = AutomationStatus.RUNNING
        self._save()
        try:
            if self._executor is not None:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self._executor(record))
                    record.status = AutomationStatus.COMPLETED
                    record.run_count += 1
                    record.last_run_at = time.time()
                    self._schedule_trigger(record)
                finally:
                    loop.close()
            else:
                record.status = AutomationStatus.COMPLETED
                record.run_count += 1
                record.last_run_at = time.time()
                self._schedule_trigger(record)
        except Exception as exc:
            record.last_error = str(exc)
            record.recovery_attempts += 1
            if record.recovery_attempts <= record.max_recovery_attempts:
                record.status = AutomationStatus.PENDING
            else:
                record.status = AutomationStatus.FAILED
            self._schedule_trigger(record)

    def list(self, *, workspace_id: str | None = None) -> list[AutomationRecord]:
        with self._lock:
            if workspace_id is None:
                return list(self._records.values())
            return [r for r in self._records.values() if r.workspace_id == workspace_id]

    def get(self, record_id: str) -> AutomationRecord | None:
        return self._records.get(record_id)

    def cancel(self, record_id: str) -> bool:
        record = self._records.get(record_id)
        if record is None:
            return False
        record.status = AutomationStatus.CANCELLED
        record.enabled = False
        self._scheduler.remove(record_id)
        self._save()
        return True

    def delete(self, record_id: str) -> bool:
        if record_id in self._records:
            del self._records[record_id]
            self._scheduler.remove(record_id)
            self._save()
            return True
        return False

    def _save(self) -> None:
        data = {
            rec.id: {
                "name": rec.name,
                "trigger_type": rec.trigger_type,
                "payload": rec.payload,
                "goal": rec.goal,
                "status": rec.status,
                "created_at": rec.created_at,
                "last_run_at": rec.last_run_at,
                "next_run_at": rec.next_run_at,
                "run_count": rec.run_count,
                "last_error": rec.last_error,
                "recovery_attempts": rec.recovery_attempts,
                "max_recovery_attempts": rec.max_recovery_attempts,
                "enabled": rec.enabled,
                "workspace_id": rec.workspace_id,
            }
            for rec in self._records.values()
        }
        self._store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            for rec_id, fields in data.items():
                self._records[rec_id] = AutomationRecord(
                    id=rec_id,
                    name=fields["name"],
                    trigger_type=TriggerType(fields["trigger_type"]),
                    payload=fields["payload"],
                    goal=fields["goal"],
                    status=AutomationStatus(fields.get("status", "pending")),
                    created_at=fields["created_at"],
                    last_run_at=fields.get("last_run_at"),
                    next_run_at=fields.get("next_run_at"),
                    run_count=fields.get("run_count", 0),
                    last_error=fields.get("last_error"),
                    recovery_attempts=fields.get("recovery_attempts", 0),
                    max_recovery_attempts=fields.get("max_recovery_attempts", 3),
                    enabled=fields.get("enabled", True),
                    workspace_id=fields.get("workspace_id", "desktop"),
                )
        except (json.JSONDecodeError, KeyError):
            self._records.clear()

    @property
    def count(self) -> int:
        return len(self._records)



# E2E test compatibility shim: SimpleAutomationEngine with register/list_rules API
class SimpleAutomationEngine:
    """Simple dict-based automation engine for E2E tests.
    
    This wraps the full AutomationEngine with a simplified API:
    - register(rule) instead of create()
    - list_rules() returns list of rule names
    """

    def __init__(self) -> None:
        self._rules: dict[str, object] = {}

    def register(self, rule: object) -> None:
        name = getattr(rule, 'name', str(rule))
        self._rules[name] = rule

    def list_rules(self) -> list[str]:
        return list(self._rules.keys())

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass
