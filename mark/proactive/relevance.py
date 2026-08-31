"""Relevance scoring for proactive events.

Each event is scored against a configurable threshold. Events below
the threshold are dropped (action=IGNORE). Events above enter the
decision pipeline (action=PROPOSE/REQUEST_APPROVAL/EXECUTE depending on risk).

Sources: vision, system, automation, learned.
Each source_type can have its own default weight.
"""
from __future__ import annotations

import time
from typing import Any

from mark.proactive.errors import (
    CODE_RELEVANCE_TOO_LOW,
    RelevanceTooLowError,
)
from mark.proactive.types import (
    EventSource,
    ProactiveAction,
    ProactiveDecision,
    ProactiveEvent,
    RiskLevel,
)

# Default relevance weights per source.
_DEFAULT_WEIGHTS: dict[EventSource, float] = {
    EventSource.VISION: 1.5,
    EventSource.SYSTEM: 1.2,
    EventSource.AUTOMATION: 1.0,
    EventSource.LEARNED: 1.3,
}

# Priority-based score multiplier (1-10, 1=highest)
_PRIORITY_MULTIPLIER: dict[int, float] = {
    1: 3.0,
    2: 2.5,
    3: 2.0,
    4: 1.5,
    5: 1.0,
    6: 0.8,
    7: 0.6,
    8: 0.4,
    9: 0.2,
    10: 0.1,
}

# Event-type boost table: certain event types are inherently more relevant.
_EVENT_TYPE_BOOST: dict[str, float] = {
    "security_alert": 3.0,
    "security_breach": 5.0,
    "system_critical": 3.0,
    "hardware_failure": 3.0,
    "network_error": 2.0,
    "permission_denied": 2.0,
    "file_modified": 1.0,
    "process_started": 0.5,
    "process_ended": 0.5,
    "memory_warning": 2.0,
    "disk_full": 3.0,
    "camera_blocked": 4.0,
    "microphone_blocked": 4.0,
    "location_change": 0.5,
    "wifi_changed": 0.3,
    "battery_low": 2.0,
    "battery_critical": 3.0,
    "power_connected": 1.0,
    "power_disconnected": 0.5,
    "user_activity": 0.8,
    "idle_timeout": 0.3,
    "app_focused": 0.2,
    "app_blur": 0.1,
    "input_detected": 0.3,
    "gesture_detected": 0.4,
    "voice_intent": 2.0,
    "automation_result": 1.0,
    "automation_failure": 2.0,
    "preference_update": 1.5,
    "learning_event": 1.0,
    "knowledge_retrieved": 0.5,
    "pattern_match": 1.0,
    "pattern_deviation": 2.0,
    "pattern_anomaly": 2.5,
}


class RelevanceFilter:
    """Score-based relevance filter for proactive events.

    Events below ``min_relevance`` are dropped.
    Scores above thresholds determine the action kind.
    """

    def __init__(
        self,
        min_relevance: float = 1.0,
        notify_threshold: float = 3.0,
        propose_threshold: float = 5.0,
        weights: dict[EventSource, float] | None = None,
        type_boosts: dict[str, float] | None = None,
    ) -> None:
        self.min_relevance = min_relevance
        self.notify_threshold = notify_threshold
        self.propose_threshold = propose_threshold
        self._weights = dict(weights) if weights is not None else dict(_DEFAULT_WEIGHTS)
        self._boosts = dict(type_boosts) if type_boosts is not None else dict(_EVENT_TYPE_BOOST)

    def evaluate(self, event: ProactiveEvent) -> ProactiveDecision:
        """Score an event and return the proactive decision."""
        score = self._compute_score(event)

        if score < self.min_relevance:
            return ProactiveDecision(
                action=ProactiveAction.IGNORE,
                event_id=event.id,
                reason=f"Score {score:.2f} below threshold {self.min_relevance}",
                risk=RiskLevel.SAFE,
            )

        if score < self.notify_threshold:
            return ProactiveDecision(
                action=ProactiveAction.NOTIFY,
                event_id=event.id,
                reason=f"Low relevance (score {score:.2f})",
                risk=RiskLevel.SAFE,
            )

        # Check priority and source for escalation
        if event.priority <= 2 or score >= self.propose_threshold:
            return ProactiveDecision(
                action=ProactiveAction.PROPOSE,
                event_id=event.id,
                reason=f"High relevance (score {score:.2f})",
                risk=RiskLevel.LOW,
            )

        if score >= 10.0:
            return ProactiveDecision(
                action=ProactiveAction.REQUEST_APPROVAL,
                event_id=event.id,
                reason=f"Critical relevance (score {score:.2f})",
                risk=RiskLevel.HIGH,
            )

        return ProactiveDecision(
            action=ProactiveAction.REMEMBER,
            event_id=event.id,
            reason=f"Moderate relevance (score {score:.2f})",
            risk=RiskLevel.SAFE,
        )

    def _compute_score(self, event: ProactiveEvent) -> float:
        score = 1.0

        # Source weight
        source_weight = self._weights.get(event.source, 1.0)
        score *= source_weight

        # Event type boost
        type_boost = self._boosts.get(event.event_type)
        if type_boost is not None:
            score += type_boost

        # Priority multiplier
        priority_mult = _PRIORITY_MULTIPLIER.get(event.priority, 1.0)
        score *= priority_mult

        # Payload-based bonuses
        payload_score = self._score_payload(event.payload)
        score += payload_score

        return score

    def _score_payload(self, payload: dict) -> float:
        """Bonus points based on payload content."""
        bonus = 0.0
        if not payload:
            return bonus

        # Keywords in payload values
        keywords_high: list[str] = [
            "error", "fail", "critical", "breach", "unauthorized",
            "unauthorized_access", "attack", "malware", "threat",
        ]
        keywords_med: list[str] = [
            "warning", "degraded", "slow", "timeout", "retry",
            "fallback", "recovery", "alert",
        ]

        for value in payload.values():
            text = str(value).lower()
            for kw in keywords_high:
                if kw in text:
                    bonus += 1.5
            for kw in keywords_med:
                if kw in text:
                    bonus += 0.5

        return bonus

    @property
    def min_relevance(self) -> float:
        return self._min

    @min_relevance.setter
    def min_relevance(self, value: float) -> None:
        if value < 0:
            raise ValueError("min_relevance must be non-negative")
        self._min = value

    @property
    def notify_threshold(self) -> float:
        return self._notify

    @notify_threshold.setter
    def notify_threshold(self, value: float) -> None:
        if value < 0:
            raise ValueError("notify_threshold must be non-negative")
        self._notify = value

    @property
    def propose_threshold(self) -> float:
        return self._propose

    @propose_threshold.setter
    def propose_threshold(self, value: float) -> None:
        if value < 0:
            raise ValueError("propose_threshold must be non-negative")
        self._propose = value
