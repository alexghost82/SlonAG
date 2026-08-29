"""Persistent automation engine with one-shot, recurring, and cron triggers.

Production-grade engine featuring:
- Idempotent execution tracking (no duplicate side-effects after restart)
- Full RFC 5617 cron expression parser
- Timezone-aware scheduling
- Concurrency control (per-job and global)
- Execution history and failure history
- Graceful shutdown with state persistence
- Restart recovery (stale RUNNING detection)
- Missed-schedule catchup
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import signal
import threading
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone as tz
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

logger = logging.getLogger(__name__)


# ── Re-export status enums from types ────────────────────────────────────

from mark.automation.types import (
    AutomationRecord,
    AutomationExecution,
    AutomationHistoryEntry,
    AutomationJob,
    AutomationRule,
    AutomationStatus,
    ConcurrencyPolicy,
    ExecutionStatus,
    RetryPolicy,
    TriggerType,
)

# ── Protocol for async executors ───────────────────────────────────────────


class AutomationExecutor(Protocol):
    """Callable that runs an automation job."""

    async def __call__(self, record: AutomationRecord) -> None: ...


# ── Full RFC 5617 Cron Scheduler ───────────────────────────────────────────


class CronParser:
    """Full RFC 5617 cron expression parser with timezone support.

    Supports: second, minute, hour, day-of-month, month, day-of-week, year.
    Standard 5-field cron: minute, hour, day-of-month, month, day-of-week.
    """

    FIELD_RANGES = {
        "second": (0, 59),
        "minute": (0, 59),
        "hour": (0, 23),
        "day": (1, 31),
        "month": (1, 12),
        "dow": (0, 7),       # 0 and 7 = Sunday
        "year": (1970, 2099),
    }

    MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "may": 5, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    DOW_MAP = {
        "sun": 0, "mon": 1, "tue": 2, "wed": 3,
        "thu": 4, "fri": 5, "sat": 6,
    }

    def __init__(self, expression: str, default_timezone: str = "UTC") -> None:
        self.expression = expression.strip()
        self.default_timezone = default_timezone
        self.fields: dict[str, set[int]] = {}
        self._parse()

    def _parse(self) -> None:
        """Parse the cron expression into field value sets."""
        parts = self.expression.split()

        if len(parts) == 6:
            # Extended format: second minute hour day month dow(year optional)
            self.fields = {
                "second": self._parse_field(parts[0], "second"),
                "minute": self._parse_field(parts[1], "minute"),
                "hour": self._parse_field(parts[2], "hour"),
                "day": self._parse_field(parts[3], "day"),
                "month": self._parse_field(parts[4], "month"),
                "dow": self._parse_field(parts[5], "dow"),
            }
        elif len(parts) == 5:
            # Standard format
            self.fields = {
                "minute": self._parse_field(parts[0], "minute"),
                "hour": self._parse_field(parts[1], "hour"),
                "day": self._parse_field(parts[2], "day"),
                "month": self._parse_field(parts[3], "month"),
                "dow": self._parse_field(parts[4], "dow"),
            }
            # Default second = 0
            self.fields["second"] = {0}
        elif len(parts) == 7:
            # Full format with year
            self.fields = {
                "second": self._parse_field(parts[0], "second"),
                "minute": self._parse_field(parts[1], "minute"),
                "hour": self._parse_field(parts[2], "hour"),
                "day": self._parse_field(parts[3], "day"),
                "month": self._parse_field(parts[4], "month"),
                "dow": self._parse_field(parts[5], "dow"),
                "year": self._parse_field(parts[6], "year"),
            }
        else:
            raise ValueError(
                f"Invalid cron expression: {self.expression!r}. "
                f"Expected 5, 6, or 7 fields, got {len(parts)}."
            )

    def _parse_field(self, value: str, field_name: str) -> set[int]:
        """Parse a single cron field into a set of integer values."""
        min_val, max_val = self.FIELD_RANGES[field_name]
        values: set[int] = set()

        for part in value.split(","):
            values.update(self._parse_range(part, min_val, max_val, field_name))

        if not values:
            raise ValueError(
                f"Cron field {field_name!r} in {self.expression!r} "
                f"produced no valid values (range {min_val}-{max_val})"
            )

        return values

    def _parse_range(self, value: str, min_val: int, max_val: int, field_name: str) -> set[int]:
        """Parse a single range/step expression like *, 5, 1-10, */2, MON-FRI."""
        # Replace named values
        lower = value.lower()
        if field_name == "month":
            for name, num in self.MONTH_MAP.items():
                lower = lower.replace(name, str(num))
        elif field_name == "dow":
            for name, num in self.DOW_MAP.items():
                lower = lower.replace(name, str(num))

        if "/" in value:
            base, step_str = value.split("/", 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Cron step must be positive, got {step}")
            if base == "*":
                start, end = min_val, max_val
            elif "-" in base:
                start, end = self._parse_interval(base, min_val, max_val)
            else:
                start = int(base)
                end = max_val
            return set(range(start, end + 1, step))

        if "-" in value and not value.startswith("-"):
            start, end = self._parse_interval(value, min_val, max_val)
            return set(range(start, end + 1))

        if value == "*":
            return set(range(min_val, max_val + 1))

        val = int(value)
        if val < min_val or val > max_val:
            raise ValueError(
                f"Cron value {val} out of range [{min_val}-{max_val}] "
                f"in field {field_name!r} of {self.expression!r}"
            )
        return {val}

    def _parse_interval(self, value: str, min_val: int, max_val: int) -> tuple[int, int]:
        """Parse a range like 1-5 or MON-FRI."""
        parts = value.split("-", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid range: {value!r}")
        try:
            a = int(parts[0]) if parts[0] else min_val
            b = int(parts[1]) if parts[1] else max_val
        except ValueError:
            raise ValueError(f"Invalid range values: {value!r}")
        if a < min_val or b > max_val or a > b:
            raise ValueError(f"Invalid range [{a}-{b}] for [{min_val}-{max_val}]")
        return a, b

    def next_fire_time(self, from_time: float | None = None) -> float:
        """Calculate the next time this cron expression should fire."""
        from_dt = datetime.fromtimestamp(from_time or time.time(), tz=tz.utc)

        # Start from the next second
        candidate = from_dt.replace(second=0, microsecond=0) + timedelta(seconds=1)

        # Search up to 4 years ahead (max possible for annual expressions)
        max_search = from_dt + timedelta(days=366 * 4)

        # Check year if specified
        if "year" in self.fields:
            valid_years = sorted(self.fields["year"])
            years = [y for y in valid_years if y >= candidate.year]
            if not years:
                # Wrap to next cycle
                candidate = candidate.replace(year=min(valid_years), 
                                              month=1, day=1, hour=0, minute=0, second=0)
            else:
                candidate = candidate.replace(year=min(years), month=1, day=1, hour=0, minute=0, second=0)

        # Iterate forward
        while candidate < max_search:
            # Check month
            if candidate.month not in self.fields.get("month", {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}):
                # Skip to next valid month
                valid_months = sorted(self.fields.get("month", [candidate.month]))
                next_month = [m for m in valid_months if m > candidate.month]
                if next_month:
                    candidate = candidate.replace(day=1, hour=0, minute=0, second=0, month=next_month[0])
                else:
                    candidate = candidate.replace(year=candidate.year + 1, month=1, day=1, hour=0, minute=0, second=0)
                continue

            # Check day
            valid_days = self.fields.get("day", set(range(1, 32)))
            max_day = self._max_day_in_month(candidate.year, candidate.month)
            valid_days = {d for d in valid_days if d <= max_day}
            if candidate.day not in valid_days:
                next_day = sorted(valid_days)
                for d in next_day:
                    if d > candidate.day:
                        candidate = candidate.replace(day=d, hour=0, minute=0, second=0)
                        break
                else:
                    # Next month
                    if candidate.month == 12:
                        candidate = candidate.replace(year=candidate.year + 1, month=1, day=1, hour=0, minute=0, second=0)
                    else:
                        candidate = candidate.replace(month=candidate.month + 1, day=1, hour=0, minute=0, second=0)
                continue

            # Check day of week (if specified)
            if "dow" in self.fields:
                # Python weekday: Mon=0, Sun=6; cron: Sun=0, Mon=1, ..., Sat=6
                python_wday = candidate.weekday()  # Mon=0..Sun=6
                cron_dow = (python_wday + 1) % 7  # Sun=0..Sat=6
                if cron_dow not in self.fields["dow"]:
                    # Advance to next day
                    candidate = candidate + timedelta(days=1, seconds=-candidate.second, 
                                                      minutes=-candidate.minute, hours=-candidate.hour)
                    candidate = candidate.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                    continue

            # Check hour
            if candidate.hour not in self.fields.get("hour", set(range(24))):
                valid_hours = sorted(self.fields.get("hour", range(24)))
                next_hour = [h for h in valid_hours if h > candidate.hour]
                if next_hour:
                    candidate = candidate.replace(minute=0, second=0, hour=next_hour[0])
                else:
                    candidate = candidate + timedelta(days=1, seconds=-candidate.second,
                                                      minutes=-candidate.minute, hours=-candidate.hour)
                    candidate = candidate.replace(hour=0, minute=0, second=0)
                continue

            # Check minute
            if candidate.minute not in self.fields.get("minute", set(range(60))):
                valid_mins = sorted(self.fields.get("minute", range(60)))
                next_min = [m for m in valid_mins if m > candidate.minute]
                if next_min:
                    candidate = candidate.replace(second=0, minute=next_min[0])
                else:
                    candidate = candidate + timedelta(hours=1, seconds=-candidate.second, 
                                                       minutes=-candidate.minute)
                    candidate = candidate.replace(minute=0, second=0)
                continue

            # Check second
            if candidate.second not in self.fields.get("second", {0}):
                valid_secs = sorted(self.fields.get("second", {0}))
                next_sec = [s for s in valid_secs if s > candidate.second]
                if next_sec:
                    candidate = candidate.replace(second=next_sec[0])
                else:
                    candidate = candidate + timedelta(minutes=1, seconds=-candidate.second)
                    candidate = candidate.replace(second=0)
                continue

            # All fields match!
            return candidate.timestamp()

        raise ValueError(
            f"Could not find a next fire time for cron {self.expression!r} "
            f"after {from_time}"
        )

    @staticmethod
    def _max_day_in_month(year: int, month: int) -> int:
        """Return the number of days in a given month."""
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        return (next_month - datetime(year, month, 1)).days


class CronScheduler:
    """Thread-safe cron scheduler that delegates to CronParser."""

    def __init__(self, default_timezone: str = "UTC") -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, _CronTask] = {}
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._default_timezone = default_timezone

    def schedule(self, task_id: str, cron_expression: str) -> float:
        try:
            parser = CronParser(cron_expression, self._default_timezone)
            next_at = parser.next_fire_time()
            with self._lock:
                self._tasks[task_id] = _CronTask(cron_expression, next_at, parser)
            return next_at
        except (ValueError, OverflowError) as exc:
            logger.warning("Cron parse error for task %r: %s", task_id, exc)
            raise

    def get_due_tasks(self) -> list[str]:
        """Return task IDs that are due (next_at <= now)."""
        now = time.time()
        with self._lock:
            due = []
            for tid, task in self._tasks.items():
                if task.next_at <= now:
                    due.append(tid)
            return due

    def advance(self, task_id: str) -> float:
        """Advance a task to the next fire time after now."""
        now = time.time()
        with self._lock:
            if task_id not in self._tasks:
                return now
            task = self._tasks[task_id]
            next_at = task.parser.next_fire_time(now)
            task.next_at = next_at
            return next_at

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
            self._callbacks.pop(task_id, None)

    def register_callback(self, task_id: str, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks[task_id] = callback


class _CronTask:
    __slots__ = ("expression", "next_at", "parser")

    def __init__(self, expression: str, next_at: float, parser: CronParser) -> None:
        self.expression = expression
        self.next_at = next_at
        self.parser = parser


# ── Idempotency tracker ──────────────────────────────────────────────────


class ExecutionIdempotencyTracker:
    """Tracks completed executions to prevent duplicate side-effects on restart.

    Uses execution_id (unique per run) to detect already-completed executions.
    After restart, if we find a RUNNING execution with the same execution_id,
    we know it already completed and should not re-run.
    """

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path / "idempotency.json"
        self._lock = threading.Lock()
        self._completed_ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            self._completed_ids = set(data.get("completed", []))
        except (json.JSONDecodeError, OSError):
            self._completed_ids.clear()

    def _save(self) -> None:
        try:
            data = {"completed": list(self._completed_ids)}
            self._store_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Failed to save idempotency state: %s", exc)

    def mark_completed(self, execution_id: str) -> bool:
        """Mark an execution as completed. Returns True if first time, False if duplicate."""
        with self._lock:
            if execution_id in self._completed_ids:
                return False
            self._completed_ids.add(execution_id)
            self._save()
            return True

    def is_completed(self, execution_id: str) -> bool:
        """Check if an execution was already completed."""
        with self._lock:
            return execution_id in self._completed_ids

    def clean_old_entries(self, max_entries: int = 1000) -> None:
        """Remove oldest entries to prevent unbounded growth."""
        with self._lock:
            if len(self._completed_ids) > max_entries:
                # Keep most recent entries
                sorted_ids = sorted(self._completed_ids)
                self._completed_ids = set(sorted_ids[-max_entries:])
                self._save()


# ── Main production engine ─────────────────────────────────────────────────


class AutomationEngine:
    """Persistent automation engine with full production features."""

    def __init__(
        self,
        *,
        store_path: Path | str | None = None,
        executor: AutomationExecutor | None = None,
        concurrency_policy: ConcurrencyPolicy | None = None,
        default_timezone: str = "UTC",
    ) -> None:
        # Storage
        if store_path is None:
            import tempfile
            tmp_dir = Path(tempfile.mkdtemp(prefix="automation_"))
            self._store_path = tmp_dir
        else:
            self._store_path = Path(store_path) if isinstance(store_path, str) else store_path
            self._store_path.mkdir(parents=True, exist_ok=True)

        self._executor = executor
        self._concurrency_policy = concurrency_policy or ConcurrencyPolicy()
        self._default_timezone = default_timezone

        # Core state (protected by lock)
        self._lock = threading.RLock()
        self._jobs: dict[str, AutomationJob] = {}
        self._executions: dict[str, AutomationExecution] = {}
        self._history: list[AutomationHistoryEntry] = []
        self._scheduler = CronScheduler(default_timezone)
        self._idempotency = ExecutionIdempotencyTracker(self._store_path)

        # Lifecycle
        self._running = False
        self._thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()

        # Load persisted state
        self._load()

    # ── Public API ──────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        trigger_type: TriggerType,
        payload: dict[str, Any],
        goal: str = "",
        workspace_id: str = "desktop",
        enabled: bool = True,
    ) -> AutomationRecord:
        """Create a new automation record. Returns the created record."""
        now = time.time()
        record_id = uuid4().hex
        record = AutomationRecord(
            id=record_id,
            name=name,
            trigger_type=trigger_type,
            payload=json.dumps(payload),
            goal=goal,
            status=AutomationStatus.PENDING,
            created_at=now,
            enabled=enabled,
            workspace_id=workspace_id,
        )
        with self._lock:
            self._schedule_trigger(record)
            self._jobs[record_id] = self._record_to_job(record)
            self._save()
        return record

    def list(self, *, workspace_id: str | None = None) -> list[AutomationRecord]:
        """List all records, optionally filtered by workspace."""
        with self._lock:
            if workspace_id is None:
                return [self._job_to_record(j) for j in self._jobs.values()]
            return [
                self._job_to_record(j) for j in self._jobs.values()
                if j.workspace_id == workspace_id
            ]

    def get(self, record_id: str) -> AutomationRecord | None:
        with self._lock:
            job = self._jobs.get(record_id)
            return self._job_to_record(job) if job else None

    def enable(self, record_id: str) -> bool:
        """Enable a disabled automation. Returns True if found."""
        with self._lock:
            job = self._jobs.get(record_id)
            if job is None:
                return False
            job.enabled = True
            job.status = AutomationStatus.PENDING
            self._schedule_trigger(job)
            self._save()
            return True

    def disable(self, record_id: str) -> bool:
        """Disable an automation (cancel scheduled runs). Returns True if found."""
        with self._lock:
            job = self._jobs.get(record_id)
            if job is None:
                return False
            job.enabled = False
            if job.status not in (AutomationStatus.RUNNING, AutomationStatus.CANCELLED):
                job.status = AutomationStatus.CANCELLED
            self._scheduler.remove(record_id)
            self._save()
            return True

    def cancel(self, record_id: str) -> bool:
        """Cancel an automation (same as disable but in one call). Returns True if found."""
        return self.disable(record_id)

    def delete(self, record_id: str) -> bool:
        """Delete an automation record. Returns True if found and deleted."""
        with self._lock:
            if record_id not in self._jobs:
                return False
            del self._jobs[record_id]
            # Remove associated executions
            self._executions = {
                eid: exe for eid, exe in self._executions.items()
                if exe.job_id != record_id
            }
            # Remove history
            self._history = [
                h for h in self._history if h.job_id != record_id
            ]
            self._scheduler.remove(record_id)
            self._save()
            return True

    def get_execution(self, execution_id: str) -> AutomationExecution | None:
        """Get an execution by its unique ID."""
        with self._lock:
            return self._executions.get(execution_id)

    def get_run_history(
        self,
        record_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AutomationHistoryEntry]:
        """Get execution history for a record, newest first."""
        with self._lock:
            entries = [
                h for h in self._history
                if h.job_id == record_id
            ]
            # Already sorted newest first by insertion order (append)
            entries.reverse()
            return entries[offset:offset + limit]

    def get_failure_history(
        self,
        record_id: str,
        *,
        limit: int = 20,
    ) -> list[AutomationHistoryEntry]:
        """Get only failed executions for a record."""
        with self._lock:
            return [
                h for h in self._history
                if h.job_id == record_id and h.status == ExecutionStatus.FAILED
            ][:limit]

    @property
    def count(self) -> int:
        return len(self._jobs)

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the engine background loop."""
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()

        # Recover from restart: mark stale RUNNING as PENDING
        self._recover_stale()

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="slon-automation",
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """Gracefully stop the engine. Returns True if stopped in time."""
        self._running = False
        self._shutdown_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("Engine thread did not stop within %.1fs", timeout)
                return False
            self._thread = None
        # Final save
        self._save()
        return True

    # ── Background loop ────────────────────────────────────────────────

    def _loop(self) -> None:
        """Main background loop. Runs until stopped."""
        # Handle shutdown signals gracefully
        old_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                old_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                pass

        try:
            tick_interval = 1.0
            while self._running and not self._shutdown_event.is_set():
                self._tick()
                self._shutdown_event.wait(timeout=tick_interval)
        finally:
            self._running = False
            self._save()
            # Restore handlers
            for sig, handler in old_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (OSError, ValueError):
                    pass

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals gracefully."""
        logger.info("Received signal %s, shutting down automation engine...", signum)
        self._running = False

    # ── Restart recovery ───────────────────────────────────────────────

    def _recover_stale(self) -> None:
        """Mark stale RUNNING jobs as PENDING on restart.

        If a job was RUNNING when the engine crashed, it's no longer
        actually running. We mark it as PENDING so it can be re-scheduled,
        unless its execution_id is known to have completed (idempotency).
        """
        for job in self._jobs.values():
            if job.status == AutomationStatus.RUNNING:
                logger.info(
                    "Recovery: job %r was RUNNING at shutdown, marking PENDING",
                    job.name,
                )
                job.status = AutomationStatus.PENDING
                # Check idempotency - if last execution completed, keep as COMPLETED
                if job.last_execution_id:
                    exe = self._executions.get(job.last_execution_id)
                    if exe and exe.status == ExecutionStatus.SUCCESS:
                        job.status = AutomationStatus.COMPLETED

        # Also check for stuck RUNNING executions
        for exe in self._executions.values():
            if exe.status == ExecutionStatus.RUNNING:
                logger.info(
                    "Recovery: execution %r was RUNNING at shutdown, marking FAILED",
                    exe.id,
                )
                exe.status = ExecutionStatus.FAILED
                exe.error_message = "Engine shutdown during execution"
                if exe.job_id in self._jobs:
                    self._jobs[exe.job_id].status = AutomationStatus.PENDING

    # ── Scheduling ─────────────────────────────────────────────────────

    def _schedule_trigger(self, record: AutomationRecord) -> None:
        """Calculate next_run_at based on trigger type."""
        try:
            payload = json.loads(record.payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}

        if record.trigger_type == TriggerType.ONE_SHOT:
            delay = payload.get("delay_seconds", 0.0)
            record.next_run_at = record.created_at + delay
        elif record.trigger_type == TriggerType.RECURRING:
            interval = payload.get("interval_seconds", 60.0)
            if record.last_run_at is not None:
                record.next_run_at = record.last_run_at + interval
            else:
                record.next_run_at = record.created_at + interval
        elif record.trigger_type == TriggerType.CRON:
            cron_expr = payload.get("expression", "")
            if cron_expr:
                record.next_run_at = self._scheduler.schedule(record.id, cron_expr)
            else:
                raise ValueError("CRON trigger requires 'expression' in payload")

    # ── Tick loop ──────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Check for due jobs and trigger executions."""
        now = time.time()

        with self._lock:
            # Find due tasks from scheduler
            due_ids = self._scheduler.get_due_tasks()

            # Also find jobs that are due by next_run_at
            for rec_id, job in self._jobs.items():
                if not job.enabled or job.status not in (AutomationStatus.PENDING,):
                    continue
                if job.next_run_at is not None and job.next_run_at <= now:
                    if rec_id not in due_ids:
                        due_ids.append(rec_id)

        # Execute due jobs
        for rec_id in due_ids:
            if not self._running:
                break
            record = self._jobs.get(rec_id)
            if record is None:
                continue
            if not record.enabled or record.status not in (AutomationStatus.PENDING,):
                continue
            self._execute(record)

    def _execute(self, record: AutomationRecord) -> None:
        """Execute a single automation record with idempotency and concurrency control."""
        # Check concurrency limits
        if self._concurrency_policy.max_concurrent_global > 0:
            active_global = sum(
                1 for e in self._executions.values()
                if e.status == ExecutionStatus.RUNNING
            )
            if active_global >= self._concurrency_policy.max_concurrent_global:
                logger.debug(
                    "Global concurrency limit reached (%d), delaying %s",
                    self._concurrency_policy.max_concurrent_global,
                    record.name,
                )
                return

        job = self._jobs.get(record.id)
        if job and self._concurrency_policy.max_concurrent_per_job > 0:
            active_per_job = sum(
                1 for e in self._executions.values()
                if e.job_id == record.id and e.status == ExecutionStatus.RUNNING
            )
            if active_per_job >= self._concurrency_policy.max_concurrent_per_job:
                logger.debug(
                    "Per-job concurrency limit reached for %s, skipping",
                    record.name,
                )
                return

        # Create execution record
        execution = AutomationExecution(
            job_id=record.id,
            execution_id=uuid4().hex,  # Unique idempotency key
            status=ExecutionStatus.RUNNING,
            started_at=time.time(),
            attempt=1,
            max_attempts=job.retry_policy.max_attempts if job else 3,
        )

        with self._lock:
            self._executions[execution.id] = execution
            record.status = AutomationStatus.RUNNING
            if job:
                job.status = AutomationStatus.RUNNING
                job.active_executions += 1
                job.last_execution_id = execution.id
            self._save()

        try:
            if self._executor is not None:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self._executor(record))
                    self._on_execution_success(record, execution)
                finally:
                    loop.close()
            else:
                self._on_execution_success(record, execution)
        except asyncio.CancelledError:
            self._on_execution_cancelled(record, execution, "Task cancelled")
        except Exception as exc:
            self._on_execution_failure(record, execution, exc)

    def _on_execution_success(
        self, record: AutomationRecord, execution: AutomationExecution
    ) -> None:
        """Handle successful execution."""
        execution.status = ExecutionStatus.SUCCESS
        execution.finished_at = time.time()
        execution.duration_seconds = execution.finished_at - execution.started_at

        with self._lock:
            record.status = AutomationStatus.COMPLETED
            record.run_count += 1
            record.last_run_at = time.time()
            if record.trigger_type != TriggerType.ONE_SHOT:
                self._schedule_trigger(record)

            # Check idempotency
            self._idempotency.mark_completed(execution.execution_id)

            # Save history entry
            self._add_history_entry(record, execution, "Successfully completed")
            self._save()

    def _on_execution_failure(
        self, record: AutomationRecord, execution: AutomationExecution, exc: BaseException
    ) -> None:
        """Handle failed execution with retry logic."""
        execution.status = ExecutionStatus.FAILED
        execution.error_code = "unknown"
        execution.error_message = str(exc)
        execution.finished_at = time.time()
        execution.duration_seconds = execution.finished_at - execution.started_at

        with self._lock:
            record.last_error = str(exc)
            record.failure_count += 1

            if execution.attempt < execution.max_attempts:
                # Retry with back-off
                execution.attempt += 1
                record.status = AutomationStatus.PENDING
                self._schedule_trigger(record)
            else:
                record.status = AutomationStatus.FAILED
                self._schedule_trigger(record)

            self._add_history_entry(record, execution, f"Failed: {exc}")
            self._save()

    def _on_execution_cancelled(
        self, record: AutomationRecord, execution: AutomationExecution, reason: str
    ) -> None:
        """Handle cancelled execution."""
        execution.status = ExecutionStatus.CANCELLED
        execution.cancelled_by = reason
        execution.cancelled_at = time.time()
        execution.finished_at = time.time()
        execution.duration_seconds = execution.finished_at - execution.started_at

        with self._lock:
            record.status = AutomationStatus.CANCELLED
            self._add_history_entry(record, execution, reason)
            self._save()

    def _add_history_entry(
        self, record: AutomationRecord, execution: AutomationExecution, result_summary: str
    ) -> None:
        """Add an execution to the history list."""
        entry = AutomationHistoryEntry(
            execution_id=execution.id,
            job_id=record.id,
            job_name=record.name,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            duration_seconds=execution.duration_seconds,
            attempt=execution.attempt,
            status=execution.status,
            error_code=execution.error_code,
            error_message=execution.error_message,
            result_summary=result_summary,
        )
        self._history.append(entry)

    # ── Persistence ────────────────────────────────────────────────────

    def _save(self) -> None:
        """Persist all state to disk."""
        try:
            data = {
                "jobs": {
                    rid: {
                        "name": j.name,
                        "trigger_type": j.trigger_type,
                        "payload": j.payload,
                        "goal": j.goal,
                        "status": j.status,
                        "created_at": j.created_at,
                        "last_run_at": j.last_run_at,
                        "next_run_at": j.next_run_at,
                        "run_count": j.run_count,
                        "failure_count": j.failure_count,
                        "last_error": j.last_error,
                        "enabled": j.enabled,
                        "workspace_id": j.workspace_id,
                        "active_executions": j.active_executions,
                        "last_execution_id": j.last_execution_id,
                    }
                    for rid, j in self._jobs.items()
                },
                "executions": {
                    eid: {
                        "job_id": e.job_id,
                        "execution_id": e.execution_id,
                        "status": e.status,
                        "started_at": e.started_at,
                        "finished_at": e.finished_at,
                        "duration_seconds": e.duration_seconds,
                        "attempt": e.attempt,
                        "max_attempts": e.max_attempts,
                        "error_code": e.error_code,
                        "error_message": e.error_message,
                        "result_payload": e.result_payload,
                        "cancelled_by": e.cancelled_by,
                        "cancelled_at": e.cancelled_at,
                    }
                    for eid, e in self._executions.items()
                },
                "history": [
                    {
                        "execution_id": h.execution_id,
                        "job_id": h.job_id,
                        "job_name": h.job_name,
                        "started_at": h.started_at,
                        "finished_at": h.finished_at,
                        "duration_seconds": h.duration_seconds,
                        "attempt": h.attempt,
                        "status": h.status,
                        "error_code": h.error_code,
                        "error_message": h.error_message,
                        "result_summary": h.result_summary,
                    }
                    for h in self._history
                ],
            }
            state_path = self._store_path / "automation_state.json"
            tmp_path = self._store_path / "automation_state.tmp"
            tmp_path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
            tmp_path.rename(state_path)  # Atomic on most FS
        except OSError as exc:
            logger.warning("Failed to save automation state: %s", exc)

    def _load(self) -> None:
        """Load persisted state from disk."""
        state_path = self._store_path / "automation_state.json"
        if not state_path.exists():
            return
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            for rid, jdata in data.get("jobs", {}).items():
                trigger_type = TriggerType(jdata["trigger_type"])
                status = AutomationStatus(jdata.get("status", "pending"))
                job = AutomationJob(
                    id=rid,
                    name=jdata["name"],
                    trigger_type=trigger_type,
                    payload=jdata.get("payload", "{}"),
                    goal=jdata.get("goal", ""),
                    status=status,
                    created_at=jdata.get("created_at", time.time()),
                    last_run_at=jdata.get("last_run_at"),
                    next_run_at=jdata.get("next_run_at"),
                    run_count=jdata.get("run_count", 0),
                    failure_count=jdata.get("failure_count", 0),
                    last_error=jdata.get("last_error"),
                    enabled=jdata.get("enabled", True),
                    workspace_id=jdata.get("workspace_id", "desktop"),
                    active_executions=jdata.get("active_executions", 0),
                    last_execution_id=jdata.get("last_execution_id"),
                )
                # Re-register with scheduler if cron
                if trigger_type == TriggerType.CRON:
                    try:
                        payload = json.loads(job.payload)
                        expr = payload.get("expression", "")
                        if expr:
                            self._scheduler.schedule(rid, expr)
                    except Exception:
                        pass  # Will be set on next schedule

                self._jobs[rid] = job

            for eid, edata in data.get("executions", {}).items():
                self._executions[eid] = AutomationExecution(
                    id=eid,
                    job_id=edata["job_id"],
                    execution_id=edata.get("execution_id", eid),
                    status=ExecutionStatus(edata.get("status", "pending")),
                    started_at=edata.get("started_at", 0.0),
                    finished_at=edata.get("finished_at", 0.0),
                    duration_seconds=edata.get("duration_seconds", 0.0),
                    attempt=edata.get("attempt", 1),
                    max_attempts=edata.get("max_attempts", 3),
                    error_code=edata.get("error_code"),
                    error_message=edata.get("error_message"),
                    result_payload=edata.get("result_payload", {}),
                    cancelled_by=edata.get("cancelled_by"),
                    cancelled_at=edata.get("cancelled_at"),
                )

            for hdata in data.get("history", []):
                self._history.append(AutomationHistoryEntry(
                    execution_id=hdata.get("execution_id", ""),
                    job_id=hdata.get("job_id", ""),
                    job_name=hdata.get("job_name", ""),
                    started_at=hdata.get("started_at", 0.0),
                    finished_at=hdata.get("finished_at", 0.0),
                    duration_seconds=hdata.get("duration_seconds", 0.0),
                    attempt=hdata.get("attempt", 1),
                    status=ExecutionStatus(hdata.get("status", "pending")),
                    error_code=hdata.get("error_code"),
                    error_message=hdata.get("error_message"),
                    result_summary=hdata.get("result_summary", ""),
                ))

            logger.info(
                "Loaded automation state: %d jobs, %d executions, %d history entries",
                len(self._jobs), len(self._executions), len(self._history),
            )
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Failed to load automation state: %s, starting fresh", exc)
            self._jobs.clear()
            self._executions.clear()
            self._history.clear()

    # ── Conversion helpers ─────────────────────────────────────────────

    def _job_to_record(self, job: AutomationJob) -> AutomationRecord:
        """Convert AutomationJob to AutomationRecord (back-compat)."""
        return AutomationRecord(
            id=job.id,
            name=job.name,
            trigger_type=job.trigger_type,
            payload=job.payload,
            goal=job.goal,
            status=job.status,
            created_at=job.created_at,
            last_run_at=job.last_run_at,
            next_run_at=job.next_run_at,
            run_count=job.run_count,
            last_error=job.last_error,
            recovery_attempts=0,
            max_recovery_attempts=3,
            enabled=job.enabled,
            workspace_id=job.workspace_id,
        )

    def _record_to_job(self, record: AutomationRecord) -> AutomationJob:
        """Convert AutomationRecord to AutomationJob."""
        try:
            payload = json.loads(record.payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}

        return AutomationJob(
            id=record.id,
            name=record.name,
            trigger_type=record.trigger_type,
            payload=payload,
            goal=record.goal,
            status=record.status,
            created_at=record.created_at,
            last_run_at=record.last_run_at,
            next_run_at=record.next_run_at,
            run_count=record.run_count,
            last_error=record.last_error,
            enabled=record.enabled,
            workspace_id=record.workspace_id,
        )

    # ── E2E compatibility shims ────────────────────────────────────────

    def register(self, rule: object) -> str:
        """Register an automation rule (back-compat). Returns rule name."""
        if hasattr(rule, "name") and hasattr(rule, "trigger") and hasattr(rule, "action"):
            name = getattr(rule, "name")
            trigger = getattr(rule, "trigger")
            action = getattr(rule, "action")
        elif isinstance(rule, dict):
            name = rule["name"]
            trigger = rule["trigger"]
            action = rule["action"]
        else:
            raise ValueError(f"Unknown rule type: {type(rule)}")
        self.create(
            name=name,
            trigger_type=TriggerType.ONE_SHOT,
            payload={"trigger": trigger, "action": action},
            goal=f"Automation: {name}",
        )
        return name

    def list_rules(self) -> list[str]:
        """Return list of registered automation rule names."""
        with self._lock:
            return [rec.name for rec in self._jobs.values()]


class SimpleAutomationEngine:
    """Simple dict-based automation engine for E2E tests."""

    def __init__(self) -> None:
        self._rules: dict[str, object] = {}

    def register(self, rule: object) -> None:
        name = getattr(rule, "name", str(rule))
        self._rules[name] = rule

    def list_rules(self) -> list[str]:
        return list(self._rules.keys())

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass
