"""Proactive Agent — event-driven proactive behavior layer.

Public API:
    from acta.proactive import ProactiveAgent, ProactiveEvent, EventSource
    agent = ProactiveAgent()
    decision = agent.ingest(ProactiveEvent(
        source=EventSource.SYSTEM,
        event_type="battery_low",
        payload={"level": 15},
    ))

Submodules:
    - anti_spam: Sliding-window spam detection
    - cooldown: Per-source cooldown enforcement
    - dedup: Content-based event deduplication
    - relevance: Scoring and threshold-based filtering
    - permissions: Permission boundary (no dangerous auto-actions)
    - safe_actions: Safe auto-executable action handlers
    - persistence: JSON-file persistence for state survival
    - types: Data types and enums
    - errors: Error codes and exceptions
"""
from __future__ import annotations

from acta.proactive.anti_spam import AntiSpamFilter
from acta.proactive.cooldown import CooldownManager
from acta.proactive.dedup import EventDedup
from acta.proactive.engine import ProactiveAgent
from acta.proactive.errors import (
    CODE_ACTION_BLOCKED,
    CODE_COOLDOWN_ACTIVE,
    CODE_DUPLICATE_EVENT,
    CODE_INVALID_ACTION,
    CODE_INVALID_EVENT,
    CODE_OK,
    CODE_PERM_DENIED,
    CODE_RELEVANCE_TOO_LOW,
    CODE_SPAM_DETECTED,
    ActionBlockedError,
    CooldownActiveError,
    DuplicateEventError,
    InvalidActionError,
    InvalidEventError,
    ProactiveError,
    RelevanceTooLowError,
    SpamDetectedError,
    proactive_message,
)
from acta.proactive.permissions import PermissionBoundary, ProactiveAuthorization
from acta.proactive.persistence import ProactivePersistence
from acta.proactive.relevance import RelevanceFilter
from acta.proactive.safe_actions import SafeActionExecutor
from acta.proactive.types import (
    EventSource,
    ProactiveAction,
    ProactiveDecision,
    ProactiveDecisionKind,
    ProactiveEvent,
    RiskLevel,
    SAFE_AUTO_ACTIONS,
)

__all__ = [
    # Main engine
    "ProactiveAgent",
    # Event/type
    "ProactiveEvent",
    "EventSource",
    "ProactiveAction",
    "ProactiveDecision",
    "ProactiveDecisionKind",
    "RiskLevel",
    "SAFE_AUTO_ACTIONS",
    # Submodules
    "AntiSpamFilter",
    "CooldownManager",
    "EventDedup",
    "RelevanceFilter",
    "PermissionBoundary",
    "ProactiveAuthorization",
    "SafeActionExecutor",
    "ProactivePersistence",
    # Errors
    "ProactiveError",
    "InvalidEventError",
    "SpamDetectedError",
    "CooldownActiveError",
    "DuplicateEventError",
    "RelevanceTooLowError",
    "ActionBlockedError",
    "InvalidActionError",
    "proactive_message",
    "CODE_OK",
    "CODE_INVALID_EVENT",
    "CODE_SPAM_DETECTED",
    "CODE_COOLDOWN_ACTIVE",
    "CODE_DUPLICATE_EVENT",
    "CODE_RELEVANCE_TOO_LOW",
    "CODE_PERM_DENIED",
    "CODE_ACTION_BLOCKED",
    "CODE_INVALID_ACTION",
]
