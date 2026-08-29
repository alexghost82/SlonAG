"""Mark Proactive Agent — production proactive layer.

Provides the ProactiveAgent orchestrator, persistence, notifications,
provenance tracking, cooldown, deduplication, relevance filtering,
and event-source registry.

All public APIs are re-exported from this package root.
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

# ── Provenance ────────────────────────────────────────────────────────────
from mark.proactive.provenance import ProvenanceTracker

# ── Filters ──────────────────────────────────────────────────────────────
from mark.proactive.filters import RelevanceFilter

# ── Cooldown & Dedup ─────────────────────────────────────────────────────
from mark.proactive.cooldown import CooldownManager
from mark.proactive.dedup import DedupManager, DedupKey

# ── Registry ──────────────────────────────────────────────────────────────
from mark.proactive.registry import EventSourceRegistry, EventSourceConfig

# ── Root-level types (re-export for convenience) ──────────────────────────
from mark.proactive.types import (
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
    # Cooldown & Dedup
    "CooldownManager",
    "DedupManager",
    "DedupKey",
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
