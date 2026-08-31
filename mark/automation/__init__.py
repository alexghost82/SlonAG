"""Persistent automation engine for one-shot, recurring, and cron triggers."""
from __future__ import annotations

from mark.automation.engine import (
    AutomationEngine,
    AutomationRecord,
    CronScheduler,
    CronParser,
    OneShotTrigger,
    RecurringTrigger,
    SimpleAutomationEngine,
)
from mark.automation.types import (
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

__all__ = [
    "AutomationEngine",
    "AutomationRecord",
    "AutomationStatus",
    "CronScheduler",
    "CronParser",
    "OneShotTrigger",
    "RecurringTrigger",
    "SimpleAutomationEngine",
    "TriggerType",
    "AutomationJob",
    "AutomationExecution",
    "AutomationHistoryEntry",
    "AutomationRule",
    "ConcurrencyPolicy",
    "ExecutionStatus",
    "RetryPolicy",
]
