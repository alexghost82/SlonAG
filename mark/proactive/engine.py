"""ProactiveAgent — the core engine.

Orchestrates relevance filtering, cooldown, dedup, provenance,
notifications, and execution of approved actions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

from mark.proactive.cooldown import CooldownManager
from mark.proactive.dedup import DedupManager, DedupKey
from mark.proactive.filters import RelevanceFilter
from mark.proactive.notifications import (
    NotificationChannel,
    NotificationEvent,
    NotificationRouter,
)
from mark.proactive.persistence import ProactiveStore
from mark.proactive.provenance import ProvenanceTracker
from mark.proactive.registry import EventSourceConfig, EventSourceRegistry
from mark.proactive.types import (
    ProactiveAction,
    ProactiveAgentConfig,
    ProactiveDecision,
    ProactiveOptInStatus,
    ProactiveResult,
    ProactiveState,
    ProactiveTrigger,
    RiskLevel,
)

logger = logging.getLogger(__name__)


class ProactiveAgent:
    """Main orchestrator for proactive event processing.

    Workflow:
      1. Validate source via registry
      2. Check rate limits
      3. Apply relevance filter
      4. Check cooldown & dedup
      5. Determine decision (ignore / notify / propose / execute)
      6. Record provenance
      7. Execute decision
      8. Persist state
    """

    def __init__(
        self,
        config: ProactiveAgentConfig | None = None,
        store: ProactiveStore | None = None,
        provenance: ProvenanceTracker | None = None,
        notification_router: NotificationRouter | None = None,
    ) -> None:
        self._config = config or ProactiveAgentConfig()
        self._store = store or ProactiveStore(path=self._config.persistence_path)
        self._provenance = provenance or ProvenanceTracker(
            persist_path=f"{self._config.persistence_path}.provenance"
        )
        self._notifications = notification_router or NotificationRouter()
        self._registry = EventSourceRegistry()
        self._filter = RelevanceFilter.from_config(self._config)
        self._cooldown = CooldownManager(default_duration=self._config.cooldown_seconds)
        self._dedup = DedupManager(window_seconds=self._config.dedup_window_seconds)

        self._state, saved_config = self._store.load()
        self._config.opt_in = saved_config.opt_in  # preserve user's opt-in

        logger.info(
            "ProactiveAgent initialized: enabled=%s opt_in=%s",
            self._config.enabled,
            self._config.opt_in.value,
        )

    # ── Registry management ──────────────────────────────────────

    def register_event_source(self, config: EventSourceConfig) -> None:
        """Register a source (vision, system, automation, etc.)."""
        self._registry.register(config)

    # ── Opt-in control ────────────────────────────────────────────────

    def set_opt_in(self, status: ProactiveOptInStatus) -> None:
        self._config.opt_in = status
        self._state.opt_in = status
        self._persist()

    @property
    def opt_in(self) -> ProactiveOptInStatus:
        return self._config.opt_in

    # ── Main processing ──────────────────────────────────────────────

    def process_trigger(self, trigger: ProactiveTrigger) -> ProactiveResult:
        """Process a trigger through the full pipeline.

        Returns a ProactiveResult with the final decision.
        """
        if not self._config.enabled:
            return self._make_result(
                trigger,
                ProactiveDecision.IGNORE,
                message="ProactiveAgent is disabled",
            )

        # 1. Validate source
        if not self._registry.is_source_enabled(trigger.source):
            return self._make_result(
                trigger,
                ProactiveDecision.IGNORE,
                message=f"Source {trigger.source.value} is not enabled",
            )

        # 2. Check rate limits
        if self._registry.is_rate_limited(trigger.source):
            return self._make_result(
                trigger,
                ProactiveDecision.IGNORE,
                message="Source rate limit exceeded",
            )

        # 3. Relevance filter
        if not self._filter.evaluate(trigger):
            return self._make_result(
                trigger,
                ProactiveDecision.IGNORE,
                message="Below relevance threshold",
            )

        # 4. Cooldown & dedup
        dedup_key = DedupKey(
            source=trigger.source.value,
            event_type=trigger.event_type,
            fingerprint=trigger.message,
        )
        dedup_id = DedupManager.fingerprint(
            trigger.source.value, trigger.event_type, trigger.message
        )
        key = f"{trigger.source.value}:{trigger.event_type}:{dedup_id}"

        if self._cooldown.is_cooldown_active(key):
            remaining = self._cooldown.time_remaining(key)
            return self._make_result(
                trigger,
                ProactiveDecision.IGNORE,
                message=f"Cooldown active ({remaining:.0f}s remaining)",
            )

        if self._dedup.is_duplicate(dedup_key):
            return self._make_result(
                trigger,
                ProactiveDecision.IGNORE,
                message="Duplicate event suppressed",
            )

        # 5. Determine decision
        decision = self._decide(trigger)

        # 6. Record provenance
        rec = self._provenance.record(trigger)
        rec.filter_result = "pass"
        rec.decision = decision.value

        # 7. Execute
        result = self._execute_decision(trigger, decision, rec)

        # 8. Persist
        self._state.total_processed += 1
        if decision == ProactiveDecision.EXECUTE:
            self._state.total_executed += 1
        if decision == ProactiveDecision.IGNORE:
            self._state.total_ignored += 1
        self._state.last_event_provenance = trigger.provenance_id

        self._cooldown.fire(key)
        self._persist()

        return result

    def _decide(self, trigger: ProactiveTrigger) -> ProactiveDecision:
        """Determine what action to take based on severity and opt-in."""
        opt_in = self._config.opt_in

        if opt_in == ProactiveOptInStatus.OFF:
            if trigger.severity == RiskLevel.CRITICAL:
                return ProactiveDecision.NOTIFY  # always notify on critical
            return ProactiveDecision.IGNORE

        if trigger.severity == RiskLevel.CRITICAL:
            return ProactiveDecision.REQUEST_APPROVAL

        if trigger.severity == RiskLevel.HIGH:
            if opt_in == ProactiveOptInStatus.AUTOMATED:
                return ProactiveDecision.REQUEST_APPROVAL
            return ProactiveDecision.PROPOSE_ACTION

        if trigger.severity == RiskLevel.MEDIUM:
            return ProactiveDecision.NOTIFY

        # LOW
        if opt_in == ProactiveOptInStatus.AUTOMATED:
            return ProactiveDecision.EXECUTE
        return ProactiveDecision.NOTIFY

    def _execute_decision(
        self,
        trigger: ProactiveTrigger,
        decision: ProactiveDecision,
        rec: Any,
    ) -> ProactiveResult:
        message = ""
        if decision == ProactiveDecision.NOTIFY:
            event = NotificationEvent(
                channel=NotificationChannel.UI,
                title="Proactive Alert",
                body=trigger.message,
                severity=trigger.severity.value,
            )
            self._notifications.send(event)
            message = f"Notified via UI: {trigger.message}"

        elif decision == ProactiveDecision.PROPOSE_ACTION:
            message = f"Proposed action for: {trigger.message}"

        elif decision == ProactiveDecision.REQUEST_APPROVAL:
            message = f"Approval requested for: {trigger.message}"

        elif decision == ProactiveDecision.EXECUTE:
            message = f"Executed low-risk action: {trigger.message}"

        self._provenance.update(
            trigger.provenance_id,
            result_status="executed",
            action_type=decision.value,
        )
        return self._make_result(trigger, decision, message=message)

    def _make_result(
        self, trigger, decision, message=""
    ) -> ProactiveResult:
        rec = self._provenance.record(trigger)
        rec.filter_result = "pass"
        rec.decision = decision.value
        rec.result_status = "suppressed" if decision == ProactiveDecision.IGNORE else "pending"
        self._provenance.update(
            trigger.provenance_id, result_status=rec.result_status
        )
        return ProactiveResult(
            trigger=trigger,
            decision=decision,
            message=message,
        )

    def _persist(self) -> None:
        self._state.last_updated_at = time.time()
        self._store.save(self._state, self._config)

    # ── State queries ────────────────────────────────────────────────

    @property
    def state(self) -> ProactiveState:
        return self._state

    @property
    def config(self) -> ProactiveAgentConfig:
        return self._config

    def get_provenance(self, event_id: str) -> Any:
        return self._provenance.get(event_id)

    def list_provenance(self, limit: int = 50) -> list[Any]:
        return self._provenance.list_all(limit=limit)

    def reset(self) -> None:
        """Reset state for testing."""
        self._cooldown = CooldownManager(default_duration=self._config.cooldown_seconds)
        self._dedup = DedupManager(window_seconds=self._config.dedup_window_seconds)
