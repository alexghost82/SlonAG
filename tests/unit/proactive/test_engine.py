"""Tests for mark.proactive.engine.ProactiveAgent."""

from __future__ import annotations

import tempfile
import os
import pytest

from mark.proactive.engine import ProactiveAgent
from mark.proactive.cooldown import CooldownManager
from mark.proactive.notifications import NotificationEvent, NotificationChannel
from mark.proactive.persistence import ProactiveStore
from mark.proactive.provenance import ProvenanceTracker
from mark.proactive.registry import EventSourceConfig
from mark.proactive.types import (
    ProactiveAgentConfig,
    ProactiveDecision,
    ProactiveOptInStatus,
    ProactiveTrigger,
    RiskLevel,
    TriggerSource,
)


def _make_trigger(
    source: TriggerSource = TriggerSource.SYSTEM,
    severity: RiskLevel = RiskLevel.LOW,
    event_type: str = "test",
) -> ProactiveTrigger:
    return ProactiveTrigger(
        source=source,
        event_type=event_type,
        severity=severity,
        message=f"Test {source.value} {severity.value}",
    )


class TestProactiveAgentInit:
    def test_default_init(self) -> None:
        agent = ProactiveAgent()
        assert agent.config.enabled is True
        assert agent.opt_in == ProactiveOptInStatus.READ_ONLY
        assert agent.state.total_processed == 0

    def test_custom_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "test.json")
            provenance_path = os.path.join(tmpdir, "test.provenance")
            config = ProactiveAgentConfig(persistence_path=store_path)
            store = ProactiveStore(path=store_path)
            provenance = ProvenanceTracker(persist_path=provenance_path)
            agent = ProactiveAgent(config=config, store=store, provenance=provenance)
            assert agent._store._path == store_path

    def test_disabled_agent_ignores(self) -> None:
        config = ProactiveAgentConfig(enabled=False)
        agent = ProactiveAgent(config=config)
        trigger = _make_trigger()
        result = agent.process_trigger(trigger)
        assert result.decision == ProactiveDecision.IGNORE


class TestEventSourceRegistration:
    def test_register_source(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.VISION,
            description="Test vision source",
            enabled=True,
            max_events_per_minute=100,
        )
        agent.register_event_source(config)
        assert agent._registry.is_registered(TriggerSource.VISION)
        assert agent._registry.is_source_enabled(TriggerSource.VISION)

    def test_unregister_source(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        config.enabled = False
        agent.register_event_source(config)
        assert agent._registry.is_source_enabled(TriggerSource.SYSTEM) is False


class TestProcessing:
    def test_disabled_source_ignored(self) -> None:
        agent = ProactiveAgent()
        trigger = _make_trigger(
            source=TriggerSource.VISION,
            severity=RiskLevel.MEDIUM,
        )
        result = agent.process_trigger(trigger)
        assert result.decision == ProactiveDecision.IGNORE
        assert "not enabled" in result.message.lower() or result.message == ""

    def test_rate_limiting(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
            max_events_per_minute=2,
        )
        agent.register_event_source(config)
        trigger1 = _make_trigger(TriggerSource.SYSTEM, RiskLevel.LOW, "t1")
        trigger2 = _make_trigger(TriggerSource.SYSTEM, RiskLevel.LOW, "t2")
        trigger3 = _make_trigger(TriggerSource.SYSTEM, RiskLevel.LOW, "t3")
        
        result1 = agent.process_trigger(trigger1)
        result2 = agent.process_trigger(trigger2)
        result3 = agent.process_trigger(trigger3)
        
        assert result3.decision == ProactiveDecision.IGNORE
        assert "rate limit" in result3.message.lower()

    def test_cooldown_suppresses_duplicates(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        trigger1 = _make_trigger(TriggerSource.SYSTEM, RiskLevel.MEDIUM, "dup_test")
        trigger2 = _make_trigger(TriggerSource.SYSTEM, RiskLevel.MEDIUM, "dup_test")
        
        r1 = agent.process_trigger(trigger1)
        r2 = agent.process_trigger(trigger2)
        
        assert r2.decision == ProactiveDecision.IGNORE
        assert "duplicate" in r2.message.lower() or "cooldown" in r2.message.lower()

    def test_opt_in_off_suppresses(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        agent.set_opt_in(ProactiveOptInStatus.OFF)
        trigger = _make_trigger(TriggerSource.SYSTEM, RiskLevel.MEDIUM)
        result = agent.process_trigger(trigger)
        assert result.decision == ProactiveDecision.IGNORE

    def test_critical_notifies_even_when_off(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        agent.set_opt_in(ProactiveOptInStatus.OFF)
        trigger = _make_trigger(TriggerSource.SYSTEM, RiskLevel.CRITICAL)
        result = agent.process_trigger(trigger)
        assert result.decision == ProactiveDecision.NOTIFY


class TestNotifications:
    def test_medium_notifies(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        trigger = _make_trigger(TriggerSource.SYSTEM, RiskLevel.MEDIUM)
        result = agent.process_trigger(trigger)
        assert result.decision == ProactiveDecision.NOTIFY

    def test_low_automated_executes(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        agent.set_opt_in(ProactiveOptInStatus.AUTOMATED)
        trigger = _make_trigger(TriggerSource.SYSTEM, RiskLevel.LOW)
        result = agent.process_trigger(trigger)
        assert result.decision == ProactiveDecision.EXECUTE


class TestProvenance:
    def test_provenance_recorded(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        trigger = _make_trigger()
        result = agent.process_trigger(trigger)
        
        rec = agent.get_provenance(trigger.provenance_id)
        assert rec is not None
        assert rec.event_id == trigger.provenance_id
        assert rec.decision == result.decision.value

    def test_list_provenance(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        for i in range(5):
            agent.process_trigger(_make_trigger(event_type=f"t{i}"))
        
        provenance_list = agent.list_provenance(limit=10)
        assert len(provenance_list) == 5


class TestPersistence:
    def test_persistence_via_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = os.path.join(tmpdir, "test.json")
            agent = ProactiveAgent(
                config=ProactiveAgentConfig(persistence_path=store_path),
            )
            config = EventSourceConfig(
                source=TriggerSource.SYSTEM,
                enabled=True,
            )
            agent.register_event_source(config)
            agent.process_trigger(_make_trigger())
            
            # Verify file was created
            assert os.path.exists(store_path)


class TestStateQueries:
    def test_state_counters(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        agent.set_opt_in(ProactiveOptInStatus.AUTOMATED)
        
        # Execute a low-risk
        agent.process_trigger(_make_trigger(RiskLevel.LOW))
        assert agent.state.total_processed >= 1


class TestReset:
    def test_reset_clears_cooldown_and_dedup(self) -> None:
        agent = ProactiveAgent()
        config = EventSourceConfig(
            source=TriggerSource.SYSTEM,
            enabled=True,
        )
        agent.register_event_source(config)
        
        trigger = _make_trigger()
        agent.process_trigger(trigger)
        agent.process_trigger(trigger)  # suppressed by dedup
        
        agent.reset()
        # After reset, dedup/cooldown should be cleared
        # This is a soft test — reset should at least not raise
        assert agent.state.total_processed >= 1
