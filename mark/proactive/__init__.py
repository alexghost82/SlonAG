"""Mark Proactive Agent — production proactive layer.

Provides the ProactiveAgent orchestrator, persistence, notifications,
provenance tracking, and event-source registry.

Re-exports from the root ``proactive.*`` submodules (types, cooldown,
dedup, policy, loop detection) so callers can import everything from
``mark.proactive``.
"""

from __future__ import annotations

# ── Core engine ──────────────────────────────────────────────────────────
from mark.proactive.engine import ProactiveAgent

# ── Persistence ──────────────────────────────────────────────────────────
from mark.proactive.persistence import ProactiveStore

# ── Notifications ────────────────────────────────────────────────────────
from mark.proactive.notifications import (
    NotificationChannel,
    NotificationEvent,
    NotificationRouter,
)

# ── Provenance ───────────────────────────────────────────────────────────
from mark.proactive.provenance import ProvenanceTracker

# ── Filters ──────────────────────────────────────────────────────────────
from mark.proactive.filters import RelevanceFilter

# ── Registry ─────────────────────────────────────────────────────────────
from mark.proactive.registry import EventSourceRegistry, EventSourceConfig

# ── Root-level types (re-export for convenience) ─────────────────────────
from proactive.types import (
    ProactiveAgentConfig,
    ProactiveDecision,
    ProactiveOptInStatus,
    ProactiveResult,
    ProactiveState,
    ProactiveTrigger,
    ProactiveAction,
    TriggerSource,
    RiskLevel,
)

__all__: list[str] = [
    # Engine
    "ProactiveAgent",
    # Persistence
    "ProactiveStore",
    # Notifications
    "NotificationChannel",
    "NotificationEvent",
    "NotificationRouter",
    # Provenance
    "ProvenanceTracker",
    # Filters
    "RelevanceFilter",
    # Registry
    "EventSourceRegistry",
    "EventSourceConfig",
    # Types
    "ProactiveAgentConfig",
    "ProactiveDecision",
    "ProactiveOptInStatus",
    "ProactiveResult",
    "ProactiveState",
    "ProactiveTrigger",
    "ProactiveAction",
    "TriggerSource",
    "RiskLevel",
]
