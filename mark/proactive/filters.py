"""Relevance filter with configurable threshold.

Filters out low-relevance triggers based on the configured
``relevance_threshold`` (0.0–1.0).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from mark.proactive.types import (
    ProactiveAgentConfig,
    ProactiveTrigger,
    RiskLevel,
    TriggerSource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelevanceFilter:
    """Evaluate whether a trigger is relevant enough to act on.

    Uses a configurable threshold plus source/risk overrides:
    - CRITICAL always passes
    - HIGH always passes
    - MEDIUM passes above threshold
    - LOW passes only if threshold <= 0.3
    """

    threshold: float = 0.5
    source_weights: dict[TriggerSource, float] | None = None
    severity_weights: dict[RiskLevel, float] | None = None

    def __post_init__(self) -> None:
        defaults: dict[TriggerSource, float] = {
            TriggerSource.VISION: 0.9,
            TriggerSource.SYSTEM: 0.7,
            TriggerSource.AUTOMATION: 0.8,
            TriggerSource.LEARNED_PATTERNS: 0.6,
            TriggerSource.MANUAL: 1.0,
        }
        object.__setattr__(self, "source_weights", self.source_weights or defaults)

        sev_defaults: dict[RiskLevel, float] = {
            RiskLevel.CRITICAL: 1.0,
            RiskLevel.HIGH: 0.95,
            RiskLevel.MEDIUM: self.threshold,
            RiskLevel.LOW: max(self.threshold * 0.3, 0.1),
        }
        object.__setattr__(self, "severity_weights", self.severity_weights or sev_defaults)

    @classmethod
    def from_config(cls, config: ProactiveAgentConfig) -> RelevanceFilter:
        return cls(threshold=config.relevance_threshold)

    def evaluate(self, trigger: ProactiveTrigger) -> bool:
        """Return True if the trigger passes the relevance threshold."""
        # CRITICAL and HIGH always pass
        if trigger.severity in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            return True

        source_w = self.source_weights.get(trigger.source, 0.5)
        severity_w = self.severity_weights.get(trigger.severity, 0.0)

        # Compute combined relevance as geometric mean
        relevance = (source_w * severity_w) ** 0.5

        passed = relevance >= self.threshold
        if not passed:
            logger.debug(
                "Relevance filter rejected source=%s severity=%s relevance=%.3f < %.2f",
                trigger.source.value,
                trigger.severity.value,
                relevance,
                self.threshold,
            )
        return passed

    def get_relevance(self, trigger: ProactiveTrigger) -> float:
        source_w = self.source_weights.get(trigger.source, 0.5)
        severity_w = self.severity_weights.get(trigger.severity, 0.0)
        return (source_w * severity_w) ** 0.5
