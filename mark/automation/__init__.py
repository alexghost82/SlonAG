"""Persistent automation engine for one-shot, recurring, and cron triggers."""
from __future__ import annotations

from mark.automation.engine import (
    AutomationEngine,
    AutomationRecord,
    AutomationStatus,
    ConcurrencyPolicy,
    CronParser,
    CronScheduler,
    ExecutionIdempotencyTracker,
    OneShotTrigger,
    RecurringTrigger,
    RetryPolicy,
    SimpleAutomationEngine,
    TriggerType,
)
from mark.automation.types import (
    AutomationExecution,
    AutomationHistoryEntry,
    AutomationJob,
    AutomationRule,
    ExecutionStatus,
)

__all__ = [
    # Engine
    "AutomationEngine",
    "SimpleAutomationEngine",
    # Records
    "AutomationRecord",
    "AutomationStatus",
    "TriggerType",
    "ExecutionStatus",
    # Triggers
    "OneShotTrigger",
    "RecurringTrigger",
    "CronScheduler",
    "CronParser",
    "ExecutionIdempotencyTracker",
    # Types
    "AutomationJob",
    "AutomationExecution",
    "AutomationHistoryEntry",
    "AutomationRule",
    # Config
    "ConcurrencyPolicy",
    "RetryPolicy",
]
