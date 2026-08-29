"""Tests for mark.proactive.types."""

from __future__ import annotations

import pytest

from mark.proactive.types import (
    ProactiveAgentConfig,
    ProactiveAction,
    ProactiveDecision,
    ProactiveOptInStatus,
    ProactiveResult,
    ProactiveState,
    ProactiveTrigger,
    RiskLevel,
    TriggerSource,
)


class TestTriggerSource:
    def test_values(self) -> None:
        assert TriggerSource.VISION == "vision"
        assert TriggerSource.SYSTEM == "system"
        assert TriggerSource.AUTOMATION == "automation"
        assert TriggerSource.LEARNED_PATTERNS == "learned_patterns"
        assert TriggerSource.MANUAL == "manual"


class TestRiskLevel:
    def test_values(self) -> None:
        assert RiskLevel.LOW == "low"
        assert RiskLevel.MEDIUM == "medium"
        assert RiskLevel.HIGH == "high"
        assert RiskLevel.CRITICAL == "critical"


class TestProactiveDecision:
    def test_values(self) -> None:
        assert ProactiveDecision.IGNORE == "ignore"
        assert ProactiveDecision.REMEMBER == "remember"
        assert ProactiveDecision.NOTIFY == "notify"
        assert ProactiveDecision.PROPOSE_ACTION == "propose_action"
        assert ProactiveDecision.REQUEST_APPROVAL == "request_approval"
        assert ProactiveDecision.EXECUTE == "execute"


class TestProactiveOptInStatus:
    def test_values(self) -> None:
        assert ProactiveOptInStatus.OFF == "off"
        assert ProactiveOptInStatus.READ_ONLY == "read_only"
        assert ProactiveOptInStatus.AUTOMATED == "automated"


class TestProactiveTrigger:
    def test_creation(self) -> None:
        trigger = ProactiveTrigger(
            source=TriggerSource.VISION,
            event_type="intrusion_detected",
            severity=RiskLevel.HIGH,
            message="Обнаружено вторжение в зону",
        )
        assert trigger.source == TriggerSource.VISION
        assert trigger.event_type == "intrusion_detected"
        assert trigger.severity == RiskLevel.HIGH
        assert trigger.message == "Обнаружено вторжение в зону"
        assert trigger.provenance_id  # non-empty
        assert trigger.created_at > 0

    def test_defaults(self) -> None:
        trigger = ProactiveTrigger(
            source=TriggerSource.SYSTEM,
            event_type="disk_full",
            severity=RiskLevel.CRITICAL,
            message="Диск заполнен",
        )
        assert trigger.details == {}


class TestProactiveAction:
    def test_creation(self) -> None:
        action = ProactiveAction(
            action_type="lock_screen",
            description="Заблокировать экран",
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            parameters={"timeout": 300},
        )
        assert action.risk_level == RiskLevel.MEDIUM
        assert action.requires_approval is True
        assert action.parameters == {"timeout": 300}


class TestProactiveState:
    def test_defaults(self) -> None:
        state = ProactiveState()
        assert state.opt_in == ProactiveOptInStatus.OFF
        assert state.enabled is True
        assert state.total_processed == 0
        assert state.total_executed == 0
        assert state.total_ignored == 0


class TestProactiveAgentConfig:
    def test_defaults(self) -> None:
        config = ProactiveAgentConfig()
        assert config.enabled is True
        assert config.opt_in == ProactiveOptInStatus.READ_ONLY
        assert config.relevance_threshold == 0.5
        assert config.cooldown_seconds == 60.0
        assert config.dedup_window_seconds == 300.0
        assert config.max_actions_per_minute == 10
        assert config.persistence_path == "memory/proactive.json"


class TestProactiveResult:
    def test_creation(self) -> None:
        trigger = ProactiveTrigger(
            source=TriggerSource.SYSTEM,
            event_type="test_event",
            severity=RiskLevel.LOW,
            message="Test",
        )
        result = ProactiveResult(
            trigger=trigger,
            decision=ProactiveDecision.IGNORE,
            message="Filtered out",
        )
        assert result.trigger == trigger
        assert result.decision == ProactiveDecision.IGNORE
        assert result.message == "Filtered out"
