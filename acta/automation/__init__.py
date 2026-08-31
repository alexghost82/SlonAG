"""Persistent automation engine for one-shot, recurring, and cron triggers."""
from __future__ import annotations

from acta.automation.engine import (
    AutomationEngine,
    AutomationRecord,
    CronScheduler,
    CronParser,
    OneShotTrigger,
    RecurringTrigger,
    SimpleAutomationEngine,
)
from acta.automation.types import (
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
