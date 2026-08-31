"""Proactive Agent Engine.

Main orchestrator that:
1. Receives events from vision, system, automation, learned patterns
2. Runs anti-spam, dedup, cooldown checks
3. Evaluates relevance
4. Applies permission boundary
5. Executes safe actions or requests approval
6. Persists state

This module does NOT modify automation, vision, memory, or AgentLoop internals.
It only exposes the event ingestion API and internal processing pipeline.
"""
from __future__ import annotations

import time
import logging
import uuid
from typing import Any, Callable

from mark.proactive.anti_spam import AntiSpamFilter
from mark.proactive.cooldown import CooldownManager
from mark.proactive.dedup import EventDedup
from mark.proactive.errors import (
    CODE_INVALID_EVENT,
    CODE_SPAM_DETECTED,
    CODE_COOLDOWN_ACTIVE,
    CODE_RELEVANCE_TOO_LOW,
    CODE_ACTION_BLOCKED,
    CODE_DUPLICATE_EVENT,
    InvalidEventError,
    SpamDetectedError,
    CooldownActiveError,
    RelevanceTooLowError,
    ActionBlockedError,
    DuplicateEventError,
)
from mark.proactive.permissions import PermissionBoundary, ProactiveAuthorization
from mark.proactive.persistence import ProactivePersistence
from mark.proactive.relevance import RelevanceFilter
from mark.proactive.safe_actions import SafeActionExecutor
from mark.proactive.types import (
    EventSource,
    ProactiveAction,
    ProactiveDecision,
    ProactiveEvent,
    ProactiveDecisionKind,
    RiskLevel,
)

logger = logging.getLogger(__name__)


# Callback types for external integration
OnDecision = Callable[[ProactiveDecision], None]
OnEventProcessed = Callable[[ProactiveEvent, ProactiveDecision], None]


class ProactiveAgent:
    """Main proactive agent engine.

    Processes incoming events through a pipeline:
    validate → anti-spam → dedup → cooldown → relevance → permissions → action

    Does NOT modify external modules (automation, vision, memory, AgentLoop).
    External modules feed events via `ingest()` or `ingest_batch()`.
    """

    def __init__(
        self,
        *,
        anti_spam_window: float = 60.0,
        anti_spam_max: int = 10,
        cooldown_default: float = 30.0,
        dedup_ttl: float = 300.0,
        dedup_max_duplicates: int = 3,
        min_relevance: float = 1.0,
        notify_threshold: float = 3.0,
        propose_threshold: float = 5.0,
        store_path: str | None = None,
        on_decision: OnDecision | None = None,
        on_event_processed: OnEventProcessed | None = None,
    ) -> None:
        self._anti_spam = AntiSpamFilter(
            window_seconds=anti_spam_window,
            max_events_per_window=anti_spam_max,
        )
        self._cooldown = CooldownManager(default_cooldown=cooldown_default)
        self._dedup = EventDedup(
            ttl=dedup_ttl,
            max_duplicates=dedup_max_duplicates,
        )
        self._relevance = RelevanceFilter(
            min_relevance=min_relevance,
            notify_threshold=notify_threshold,
            propose_threshold=propose_threshold,
        )
        self._permissions = PermissionBoundary()
        self._authorization = ProactiveAuthorization()
        self._executor = SafeActionExecutor()
        self._persistence = ProactivePersistence(store_path=store_path)
        self._on_decision = on_decision
        self._on_event_processed = on_event_processed

        # Load persisted state
        self._persistence.load()

        # Load cooldowns
        self._cooldown_overrides: dict[str, CooldownEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, event: ProactiveEvent) -> ProactiveDecision:
        """Process a single proactive event through the full pipeline.

        Returns the final decision. Raises ProactiveError for
        structural errors (spam, cooldown, duplicate).
        """
        if event is None or not isinstance(event, ProactiveEvent):
            raise InvalidEventError("Event must be a ProactiveEvent instance.")

        if not event.event_type:
            raise InvalidEventError("Event must have a non-empty event_type.")

        # Step 1: Anti-spam check
        if not self._anti_spam.check(event):
            raise SpamDetectedError(
                f"Event type '{event.event_type}' exceeded spam rate limit."
            )

        # Step 2: Dedup check
        if self._dedup.is_duplicate(event):
            raise DuplicateEventError(
                f"Duplicate event (fingerprint collapsed within TTL)."
            )

        # Step 3: Cooldown check
        if self._cooldown.is_on_cooldown(event.event_type):
            remaining = self._cooldown.get_remaining(event.event_type)
            raise CooldownActiveError(
                f"Cooldown active for '{event.event_type}'. "
                f"Remaining: {remaining:.1f}s."
            )

        # Step 4: Relevance evaluation
        decision = self._relevance.evaluate(event)

        # Step 5: Permission boundary
        decision = self._permissions.evaluate(decision)

        # Step 6: Action execution
        decision = self._execute_decision(decision, event)

        # Start cooldown for the event type
        self._cooldown.start_cooldown(event.event_type)

        # Persist
        self._persistence.save_decision(decision)

        # Callbacks
        if self._on_decision:
            self._on_decision(decision)
        if self._on_event_processed:
            self._on_event_processed(event, decision)

        logger.info(
            "Proactive decision: event=%s action=%s risk=%s",
            event.id[:8],
            decision.action.value,
            decision.risk.name,
        )

        return decision

    def ingest_batch(self, events: list[ProactiveEvent]) -> list[ProactiveDecision]:
        """Process a batch of events. Skips invalid/duplicate/spam events."""
        decisions: list[ProactiveDecision] = []
        for event in events:
            try:
                decision = self.ingest(event)
                decisions.append(decision)
            except (SpamDetectedError, DuplicateEventError, CooldownActiveError):
                # Silently skip spam/duplicate/cooldown events in batch mode
                continue
            except InvalidEventError:
                logger.warning("Skipping invalid event: %s", event)
                continue
        return decisions

    def approve_event(self, event_id: str) -> None:
        """User approves a pending event. Allows auto-execution."""
        self._authorization.approve(event_id)

    def reject_event(self, event_id: str) -> None:
        """User rejects a pending event."""
        self._authorization.reject(event_id)

    def get_pending_approvals(self) -> list[ProactiveDecision]:
        """Return decisions that require user approval."""
        # In a real system this would query persistence.
        # For now, decisions are already persisted; this is a stub.
        return []

    def configure(
        self,
        min_relevance: float | None = None,
        notify_threshold: float | None = None,
        propose_threshold: float | None = None,
        anti_spam_window: float | None = None,
        anti_spam_max: int | None = None,
        cooldown_default: float | None = None,
    ) -> None:
        """Update configuration at runtime."""
        if min_relevance is not None:
            self._relevance.min_relevance = min_relevance
        if notify_threshold is not None:
            self._relevance.notify_threshold = notify_threshold
        if propose_threshold is not None:
            self._relevance.propose_threshold = propose_threshold
        if anti_spam_window is not None:
            self._anti_spam._window = anti_spam_window
        if anti_spam_max is not None:
            self._anti_spam._max = anti_spam_max
        if cooldown_default is not None:
            self._cooldown._default_cooldown = cooldown_default

    def clear(self) -> None:
        """Reset all state (anti-spam, cooldown, dedup, permissions)."""
        self._anti_spam.clear_expired()
        self._dedup.clear_expired()
        self._cooldown = CooldownManager(
            default_cooldown=self._cooldown._default_cooldown
        )
        self._authorization = ProactiveAuthorization()
        self._persistence.save()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _execute_decision(
        self,
        decision: ProactiveDecision,
        event: ProactiveEvent,
    ) -> ProactiveDecision:
        """Execute the action or mark for approval."""
        if decision.action == ProactiveAction.EXECUTE:
            if self._authorization.is_approved(event.id):
                try:
                    self._executor.execute(decision)
                except Exception:
                    logger.exception("Safe action execution failed")
                    decision = ProactiveDecision(
                        action=ProactiveAction.REQUEST_APPROVAL,
                        event_id=decision.event_id,
                        reason="Execution failed, requires approval",
                        risk=RiskLevel.HIGH,
                        details=decision.details,
                        approval_required=True,
                    )
            else:
                # Not approved yet, escalate
                decision = ProactiveDecision(
                    action=ProactiveAction.REQUEST_APPROVAL,
                    event_id=decision.event_id,
                    reason="Event requires user approval before execution",
                    risk=RiskLevel.HIGH,
                    details=decision.details,
                    approval_required=True,
                )

        elif decision.action == ProactiveAction.PROPOSE:
            # Auto-execute if the proposed action is safe
            details = event.payload
            action_name = details.get("action_name", "")
            if action_name in self._permissions.allow_list:
                decision = ProactiveDecision(
                    action=ProactiveAction.EXECUTE,
                    event_id=decision.event_id,
                    reason="Safe action auto-executed",
                    risk=RiskLevel.SAFE,
                    details=details,
                    approval_required=False,
                )
                try:
                    self._executor.execute(decision)
                except Exception:
                    logger.exception("Auto-execute of safe action failed")
            # else: keep as PROPOSE for the caller to review

        elif decision.action == ProactiveAction.NOTIFY:
            details = event.payload
            details.setdefault("title", "Proactive Alert")
            details.setdefault("message", decision.reason)
            decision = ProactiveDecision(
                action=ProactiveAction.EXECUTE,
                event_id=decision.event_id,
                reason="Notified",
                risk=RiskLevel.SAFE,
                details=details,
                approval_required=False,
            )
            try:
                self._executor.execute(decision)
            except Exception:
                logger.exception("Notify action failed")
                decision = ProactiveDecision(
                    action=ProactiveAction.PROPOSE,
                    event_id=decision.event_id,
                    reason="Notify failed, proposal required",
                    risk=RiskLevel.LOW,
                    details=decision.details,
                    approval_required=False,
                )

        elif decision.action == ProactiveAction.REMEMBER:
            details = event.payload
            details.setdefault("data", dict(event.payload))
            decision = ProactiveDecision(
                action=ProactiveAction.EXECUTE,
                event_id=decision.event_id,
                reason="Event remembered",
                risk=RiskLevel.SAFE,
                details=details,
                approval_required=False,
            )
            try:
                self._executor.execute(decision)
            except Exception:
                logger.exception("Remember action failed")

        elif decision.action == ProactiveAction.IGNORE:
            # Already correct
            pass

        elif decision.action == ProactiveAction.REQUEST_APPROVAL:
            decision.approval_required = True

        return decision
