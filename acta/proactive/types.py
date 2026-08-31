"""Data types for the proactive agent system."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4


class EventSource(StrEnum):
    """Where the event originates."""
    VISION = "vision"
    SYSTEM = "system"
    AUTOMATION = "automation"
    LEARNED = "learned"


class ProactiveAction(StrEnum):
    """Actions the proactive engine can take."""
    IGNORE = "ignore"
    REMEMBER = "remember"
    NOTIFY = "notify"
    PROPOSE = "propose_action"
    REQUEST_APPROVAL = "request_approval"
    EXECUTE = "execute"


class ProactiveDecisionKind(StrEnum):
    """Decision outcome from relevance filtering."""
    DROP = "drop"
    PROCESS = "process"
    ESCALATE = "escalate"


class RiskLevel(IntEnum):
    """Risk of a proactive action. SAFE is lowest, DANGEROUS is highest."""
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    DANGEROUS = 4


# Events that can be auto-executed by proactive agent without user approval.
# Only these low-risk, already-authorized patterns are allowed.
SAFE_AUTO_ACTIONS: frozenset[str] = frozenset({
    "notify",
    "remember",
    "check_status",
    "log_event",
    "update_health",
})


@dataclass(frozen=True)
class ProactiveEvent:
    """An event from vision, system, automation, or learned patterns."""

    id: str = field(default_factory=lambda: uuid4().hex)
    source: EventSource = EventSource.SYSTEM
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    provenance: str = ""  # chain-of-origin identifier
    priority: int = 5  # 1=critical, 10=lowest


@dataclass(frozen=True)
class ProactiveDecision:
    """Decision made by the proactive layer."""

    action: ProactiveAction
    event_id: str
    reason: str
    risk: RiskLevel = RiskLevel.SAFE
    details: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False


@dataclass
class AntiSpamSnapshot:
    """State for spam detection: last N events of same type."""

    type: str
    window_seconds: float  # sliding window duration
    max_count: int  # max events allowed in window
    timestamps: list[float] = field(default_factory=list)


@dataclass
class DedupState:
    """Deduplication state for near-identical events."""

    fingerprint: str  # hash of normalized event content
    last_seen_at: float  # last time seen
    count: int  # how many duplicate events
    resolved: bool = False  # whether user already handled it


@dataclass
class CooldownEntry:
    """Cooldown state: source_type → next allowed time."""

    source_type: str
    cooldown_seconds: float
    next_allowed: float = 0.0
    count: int = 0

    def is_active(self, now: float | None = None) -> bool:
        check_time = now or __import__("time").time()
        return check_time < self.next_allowed

    def expire(self) -> None:
        """Mark as expired so next check starts the window fresh."""
        self.next_allowed = __import__("time").time()
        self.count = 0
