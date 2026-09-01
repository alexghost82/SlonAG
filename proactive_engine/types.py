"""Proactive agent — types, enums and dataclasses.

The bounded proactive agent reacts to external/internal triggers only
when opt-in is enabled, relevance and policy checks pass, and no loop
or cooldown block the execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class TriggerSource(Enum):
    """Where a proactive trigger originates."""

    AUTOMATION = "automation"
    MONITORED_CONDITION = "monitored_condition"
    VISION_EVENT = "vision_event"
    SYSTEM_EVENT = "system_event"
    USER_WORKFLOW = "user_workflow"


class ProactiveAction(Enum):
    """What the proactive agent does after approval."""

    NOTIFY = "notify"
    PROPOSE = "propose"
    EXECUTE = "execute"


class ProactiveState(Enum):
    """Lifecycle of a proactive trigger."""

    PENDING = "pending"
    RELEVANT = "relevant"
    DEDUPED = "deduped"
    COOLDOWN = "cooldown"
    POLICY_BLOCKED = "policy_blocked"
    NOTIFIED = "notified"
    PROPOSED = "proposed"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    LOOP_BLOCKED = "loop_blocked"


class ProactiveOptInStatus(Enum):
    """User opt-in states."""

    OFF = "off"
    NOTIFY_ONLY = "notify_only"
    NOTIFY_AND_PROPOSE = "notify_and_propose"
    FULL_AUTO = "full_auto"


class RiskLevel(Enum):
    """Risk tiers for proactive actions."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ProactiveTrigger:
    """A single event that may spawn proactive action."""

    source: TriggerSource
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    priority: float = 1.0  # higher = more urgent


@dataclass
class ProactiveDecision:
    """Result of the pipeline for one trigger."""

    trigger: ProactiveTrigger
    action: ProactiveAction
    reason: str
    state: ProactiveState
    loop_check: bool = True
    risk: RiskLevel = RiskLevel.SAFE
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return self.state in (
            ProactiveState.DEDUPED,
            ProactiveState.COOLDOWN,
            ProactiveState.POLICY_BLOCKED,
            ProactiveState.LOOP_BLOCKED,
        )

    @property
    def allows_execution(self) -> bool:
        return self.state == ProactiveState.EXECUTED


@dataclass
class ProactiveRecord:
    """Persisted record of a proactive trigger + decision."""

    trigger_id: str
    action: ProactiveAction
    state: ProactiveState
    reason: str
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    loop_count: int = 0
    dedup_key: str | None = None
    last_cooldown_end: float | None = None
    result_summary: str | None = None

    def complete(self, result: str | None = None) -> None:
        self.state = ProactiveState.EXECUTED
        self.completed_at = time.time()
        self.result_summary = result


@dataclass
class QuietPeriod:
    """A time window during which no proactive triggers fire."""

    start: float  # 0.0-24.0, hours of day
    end: float    # 0.0-24.0, hours of day

    @property
    def active(self) -> bool:
        now = time.localtime()
        current_hour = now.tm_hour + now.tm_min / 60.0
        if self.start <= self.end:
            return self.start <= current_hour < self.end
        # Overnight: e.g. 22:00 - 06:00
        return current_hour >= self.start or current_hour < self.end

    @property
    def remaining(self) -> float:
        now = time.localtime()
        current_hour = now.tm_hour + now.tm_min / 60.0
        if self.start <= self.end:
            if not (self.start <= current_hour < self.end):
                return 0.0
            return (self.end - current_hour) * 3600
        # Overnight
        if current_hour >= self.start:
            return (self.end + 24.0 - current_hour) * 3600
        return (self.end - current_hour) * 3600


@dataclass
class ProactiveAgentConfig:
    """Configuration for the bounded proactive agent."""

    enabled: bool = False
    action_mode: ProactiveOptInStatus = ProactiveOptInStatus.OFF
    cooldown_seconds: float = 300.0
    quiet_hours_start: float | None = None
    quiet_hours_end: float | None = None
    max_loop_count: int = 3
    max_allowed_risk: RiskLevel = RiskLevel.MEDIUM
    max_triggers_per_minute: int = 10
    trigger_cooldowns: dict[str, float] = field(default_factory=dict)

    @property
    def quiet_periods(self) -> list[QuietPeriod]:
        if self.quiet_hours_start is not None and self.quiet_hours_end is not None:
            return [QuietPeriod(self.quiet_hours_start, self.quiet_hours_end)]
        return []

    def effective_cooldown(self, event_type: str) -> float:
        return self.trigger_cooldowns.get(event_type, self.cooldown_seconds)


@dataclass
class ProactiveResult:
    """Final result after AgentLoop + tool execution."""

    trigger_id: str
    action: ProactiveAction
    state: ProactiveState
    loop_iterations: int = 0
    tool_calls_made: int = 0
    result_summary: str = ""
    error: str | None = None
    completed_at: float = field(default_factory=time.time)
