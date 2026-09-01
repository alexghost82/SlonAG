"""Canonical automation data models.

All scheduling, execution, and history types live here so the engine
and the action layer can share them without circular imports."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

# ── Trigger types ──────────────────────────────────────────────────────────

class TriggerType(StrEnum):
    ONE_SHOT = "one_shot"           # fire once, then retire
    RECURRING = "recurring"         # fire at fixed interval
    CRON = "cron"                   # cron expression (RFC 561)


class AutomationStatus(StrEnum):
    PENDING    = "pending"
    SCHEDULED  = "scheduled"        # waiting for next_run
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class ExecutionStatus(StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


# ── Engine configuration ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RetryPolicy:
    """Max retries and back-off strategy for failed executions."""

    max_attempts: int = 3                # total tries (1 original + retries)
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    retryable_codes: frozenset[str] = field(
        default_factory=lambda: frozenset({"transient", "timeout", "rate_limit"})
    )


@dataclass(frozen=True)
class ConcurrencyPolicy:
    """Limits on concurrent executions per job or globally."""

    max_concurrent_per_job: int = 1      # one execution at a time per job
    max_concurrent_global: int = 4               # global cap across all jobs


# ── Job (schedule) ─────────────────────────────────────────────────────────

@dataclass
class AutomationJob:
    """A persisted automation schedule (the job definition)."""

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = ""
    trigger_type: TriggerType = TriggerType.ONE_SHOT
    # ── trigger parameters ─────────────────────────────────────────────
    cron_expression: str = ""            # e.g. "0 9 * * 1-5" for cron
    interval_seconds: float = 0.0        # positive for recurring
    # ── execution params ───────────────────────────────────────────────
    payload: dict[str, Any] = field(default_factory=dict)  # tool args dict
    goal: str = ""
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    # ── state ────────────────────────────────────────────────────────────
    status: AutomationStatus = AutomationStatus.PENDING
    enabled: bool = True
    workspace_id: str = "desktop"
    timezone_str: str = "UTC"
    # ── scheduling ───────────────────────────────────────────────────────
    created_at: float = field(default_factory=lambda: time.time())
    next_run_at: float | None = None
    last_run_at: float | None = None
    # ── history counters ────────────────────────────────────────────────
    run_count: int = 0
    failure_count: int = 0
    total_attempts: int = 0
    # ── safety ───────────────────────────────────────────────────────────
    side_effect_safe: bool = True        # True = auto-retry; False = pause on failure
    last_error: str | None = None
    # ── concurrency tracking ─────────────────────────────────────────────
    active_executions: int = 0
    last_execution_id: str | None = None


# ── Execution (run) ────────────────────────────────────────────────────────

@dataclass
class AutomationExecution:
    """One run of an AutomationJob."""

    id: str = field(default_factory=lambda: uuid4().hex)
    job_id: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_seconds: float = 0.0
    attempt: int = 1
    max_attempts: int = 3
    error_code: str | None = None
    error_message: str | None = None
    result_payload: dict[str, Any] = field(default_factory=dict)
    cancelled_by: str | None = None
    cancelled_at: float | None = None


# ── History entry ──────────────────────────────────────────────────────────

@dataclass
class AutomationHistoryEntry:
    """Human-readable history record for an execution."""

    execution_id: str = ""
    job_id: str = ""
    job_name: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_seconds: float = 0.0
    attempt: int = 1
    status: ExecutionStatus = ExecutionStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None
    result_summary: str = ""


# E2E test compatibility shim: simplified AutomationRule for simple dict-based rules

@dataclass
class AutomationRule:
    """Simple automation rule for E2E tests (simpler than AutomationJob)."""
    name: str = ""
    trigger: str | dict[str, Any] = "manual"
    action: str | dict[str, Any] = ""
    enabled: bool = True
    params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.params is None:
            self.params = {}
