"""Proactive Agent core types — enums, dataclasses, and TypedDicts.

All modules in ``mark.proactive`` import from here to stay consistent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Trigger source
# ---------------------------------------------------------------------------

class TriggerSource(StrEnum):
    """Where a proactive event originates."""

    VISION = "vision"
    SYSTEM = "system"
    AUTOMATION = "automation"
    LEARNED_PATTERNS = "learned_patterns"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Risk level
# ---------------------------------------------------------------------------

class RiskLevel(StrEnum):
    """Severity classification for proactive actions."""

    LOW = "low"                    # read-only, non-disruptive
    MEDIUM = "medium"              # informational, minor state change
    HIGH = "high"                  # requires explicit user approval
    CRITICAL = "critical"          # destructive, irreversible


# ---------------------------------------------------------------------------
# Decision & action
# ---------------------------------------------------------------------------

class ProactiveDecision(StrEnum):
    """What the ProactiveAgent chose to do with an event."""

    IGNORE = "ignore"
    REMEMBER = "remember"
    NOTIFY = "notify"
    PROPOSE_ACTION = "propose_action"
    REQUEST_APPROVAL = "request_approval"
    EXECUTE = "execute"


# ---------------------------------------------------------------------------
# Opt-in status
# ---------------------------------------------------------------------------

class ProactiveOptInStatus(StrEnum):
    """User's opt-in state for proactive automation."""

    OFF = "off"
    READ_ONLY = "read_only"        # notify + propose only, no execute
    AUTOMATED = "automated"        # execute low-risk automatically


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProactiveTrigger:
    """An event that may trigger proactive behaviour."""

    source: TriggerSource
    event_type: str                # domain-specific identifier
    severity: RiskLevel
    message: str                   # human-readable (Russian)
    details: dict[str, Any] = field(default_factory=dict)
    provenance_id: str = field(
        default_factory=lambda: uuid.uuid4().hex[:12]
    )
    created_at: float = field(
        default_factory=lambda: __import__("time").time()
    )


@dataclass(frozen=True)
class ProactiveAction:
    """An action the agent may perform."""

    action_type: str               # e.g. "lock_screen", "send_notification"
    description: str               # human-readable
    risk_level: RiskLevel
    requires_approval: bool
    parameters: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Result / state
# ---------------------------------------------------------------------------

@dataclass
class ProactiveResult:
    """Outcome of processing a single trigger."""

    trigger: ProactiveTrigger
    decision: ProactiveDecision
    action: ProactiveAction | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProactiveState:
    """Current state snapshot of the ProactiveAgent (for persistence & restart)."""

    opt_in: ProactiveOptInStatus = ProactiveOptInStatus.OFF
    enabled: bool = True
    total_processed: int = 0
    total_executed: int = 0
    total_ignored: int = 0
    last_event_provenance: str | None = None
    last_updated_at: float = field(
        default_factory=lambda: __import__("time").time()
    )


@dataclass
class ProactiveAgentConfig:
    """Configuration for the ProactiveAgent."""

    enabled: bool = True
    opt_in: ProactiveOptInStatus = ProactiveOptInStatus.READ_ONLY
    relevance_threshold: float = 0.5          # 0.0 – 1.0
    cooldown_seconds: float = 60.0            # minimum interval between similar events
    dedup_window_seconds: float = 300.0       # window for deduplication
    max_actions_per_minute: int = 10
    log_level: str = "INFO"
    persistence_path: str = "memory/proactive.json"


__all__ = [
    "TriggerSource",
    "RiskLevel",
    "ProactiveDecision",
    "ProactiveOptInStatus",
    "ProactiveTrigger",
    "ProactiveAction",
    "ProactiveResult",
    "ProactiveState",
    "ProactiveAgentConfig",
]
