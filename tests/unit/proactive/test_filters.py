"""Tests for mark.proactive.filters.RelevanceFilter."""

from __future__ import annotations

import pytest

from mark.proactive.filters import RelevanceFilter
from mark.proactive.types import (
    ProactiveTrigger,
    RiskLevel,
    TriggerSource,
)


class TestRelevanceFilter:
    def test_critical_always_passes(self) -> None:
        f = RelevanceFilter(threshold=0.9)
        trigger = ProactiveTrigger(
            source=TriggerSource.LEARNED_PATTERNS,
            event_type="anomaly",
            severity=RiskLevel.CRITICAL,
            message="Critical anomaly",
        )
        assert f.evaluate(trigger) is True

    def test_high_always_passes(self) -> None:
        f = RelevanceFilter(threshold=0.9)
        trigger = ProactiveTrigger(
            source=TriggerSource.AUTOMATION,
            event_type="failover",
            severity=RiskLevel.HIGH,
            message="Failover initiated",
        )
        assert f.evaluate(trigger) is True

    def test_low_rejected_above_threshold(self) -> None:
        f = RelevanceFilter(threshold=0.5)
        trigger = ProactiveTrigger(
            source=TriggerSource.MANUAL,
            event_type="noise",
            severity=RiskLevel.LOW,
            message="Low priority",
        )
        # MANUAL=1.0 * LOW ~0.15 -> sqrt(0.15) ~ 0.387 < 0.5
        assert f.evaluate(trigger) is False

    def test_medium_above_threshold(self) -> None:
        f = RelevanceFilter(threshold=0.5)
        trigger = ProactiveTrigger(
            source=TriggerSource.VISION,
            event_type="motion",
            severity=RiskLevel.MEDIUM,
            message="Motion detected",
        )
        # VISION=0.9 * MEDIUM=0.5 -> sqrt(0.45) ~ 0.67 > 0.5
        assert f.evaluate(trigger) is True

    def test_get_relevance(self) -> None:
        f = RelevanceFilter(threshold=0.5)
        trigger = ProactiveTrigger(
            source=TriggerSource.VISION,
            event_type="test",
            severity=RiskLevel.CRITICAL,
            message="Test",
        )
        rel = f.get_relevance(trigger)
        assert 0.94 <= rel <= 0.95  # VISION(0.9) * CRITICAL(1.0) -> sqrt(0.9) ~ 0.949 

    def test_custom_weights(self) -> None:
        weights = {TriggerSource.MANUAL: 0.1}
        f = RelevanceFilter(threshold=0.5, source_weights=weights)
        trigger = ProactiveTrigger(
            source=TriggerSource.MANUAL,
            event_type="manual_trigger",
            severity=RiskLevel.HIGH,
            message="Manual high",
        )
        # MANUAL=0.1 * HIGH=0.95 -> sqrt(0.095) ~ 0.31 < 0.5
        assert f.evaluate(trigger) is False

    def test_from_config(self) -> None:
        from mark.proactive.types import ProactiveAgentConfig
        config = ProactiveAgentConfig(relevance_threshold=0.7)
        f = RelevanceFilter.from_config(config)
        assert f.threshold == 0.7

    def test_source_weight_overrides(self) -> None:
        f = RelevanceFilter(threshold=0.5)
        # VISION=0.9 always passes with HIGH/CRITICAL
        for source in TriggerSource:
            for severity in RiskLevel:
                trigger = ProactiveTrigger(
                    source=source,
                    event_type="test",
                    severity=severity,
                    message="Test",
                )
                if severity == RiskLevel.CRITICAL:
                    assert f.evaluate(trigger) is True, f"{source}/{severity}"
                elif severity == RiskLevel.HIGH:
                    assert f.evaluate(trigger) is True, f"{source}/{severity}"
