"""Bounded proactive agent — public API.

Usage:
    from proactive import ProactiveEngine

    engine = ProactiveEngine.from_settings(settings)
    engine.start()

    # Push a trigger from any source
    engine.push_trigger(
        trigger=ProactiveTrigger(
            source=TriggerSource.SYSTEM_EVENT,
            event_type="disk_low",
            payload={"path": "/data", "free_pct": 5},
        )
    )

    engine.stop()
"""

from proactive.engine import ProactiveEngine
from proactive.types import (
    ProactiveAgentConfig,
    ProactiveDecision,
    ProactiveOptInStatus,
    ProactiveResult,
    ProactiveState,
    ProactiveTrigger,
    ProactiveAction,
    TriggerSource,
    QuietPeriod,
    RiskLevel,
    ProactiveRecord,
)

__all__ = [
    "ProactiveEngine",
    "ProactiveAgentConfig",
    "ProactiveDecision",
    "ProactiveOptInStatus",
    "ProactiveResult",
    "ProactiveState",
    "ProactiveTrigger",
    "ProactiveAction",
    "TriggerSource",
    "QuietPeriod",
    "RiskLevel",
    "ProactiveRecord",
]
