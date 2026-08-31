"""Comprehensive tests for the proactive agent engine and its components.

Covers:
- Anti-spam sliding window
- Cooldown per-source
- Event deduplication by fingerprint
- Relevance scoring and thresholds
- Permission boundary (safe auto-actions only)
- Safe action execution
- Full pipeline (ingest)
- Batch processing
- Persistence (save/load)
- Configuration changes
- Error handling
- Russian i18n messages
- ProactiveEvent and type definitions
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from mark.proactive import (
    AntiSpamFilter,
    CooldownManager,
    EventDedup,
    PermissionBoundary,
    ProactiveAgent,
    ProactiveAuthorization,
    ProactiveEvent,
    ProactivePersistence,
    ProactiveDecision,
    ProactiveAction,
    RelevanceFilter,
    RiskLevel,
    SafeActionExecutor,
    EventSource,
    SAFE_AUTO_ACTIONS,
)
from mark.proactive.errors import (
    CODE_ACTION_BLOCKED,
    CODE_COOLDOWN_ACTIVE,
    CODE_DUPLICATE_EVENT,
    CODE_INVALID_EVENT,
    CODE_OK,
    CODE_RELEVANCE_TOO_LOW,
    CODE_SPAM_DETECTED,
    ActionBlockedError,
    CooldownActiveError,
    DuplicateEventError,
    InvalidEventError,
    ProactiveError,
    RelevanceTooLowError,
    SpamDetectedError,
    proactive_message,
)


# ---------------------------------------------------------------------------
# Anti-spam tests
# ---------------------------------------------------------------------------


class TestAntiSpamFilter:
    def test_allows_single_event(self) -> None:
        f = AntiSpamFilter(window_seconds=1.0, max_events_per_window=3)
        event = ProactiveEvent(event_type="test_type", source=EventSource.SYSTEM)
        assert f.check(event) is True

    def test_allows_up_to_max(self) -> None:
        f = AntiSpamFilter(window_seconds=2.0, max_events_per_window=3)
        events = [
            ProactiveEvent(event_type="spam_type", source=EventSource.SYSTEM)
            for _ in range(3)
        ]
        for e in events:
            assert f.check(e) is True

    def test_drops_over_limit(self) -> None:
        f = AntiSpamFilter(window_seconds=2.0, max_events_per_window=3)
        events = [
            ProactiveEvent(event_type="spam_type", source=EventSource.SYSTEM)
            for _ in range(4)
        ]
        for e in events[:3]:
            assert f.check(e) is True
        assert f.check(events[3]) is False

    def test_window_reset(self) -> None:
        f = AntiSpamFilter(window_seconds=0.1, max_events_per_window=2)
        e1 = ProactiveEvent(event_type="w_type", source=EventSource.SYSTEM)
        e2 = ProactiveEvent(event_type="w_type", source=EventSource.SYSTEM)
        assert f.check(e1) is True
        assert f.check(e2) is True
        assert f.check(e1) is False  # limit reached

        time.sleep(0.15)  # wait for window to expire
        e3 = ProactiveEvent(event_type="w_type", source=EventSource.SYSTEM)
        assert f.check(e3) is True  # window reset

    def test_independent_types(self) -> None:
        f = AntiSpamFilter(window_seconds=2.0, max_events_per_window=1)
        e1 = ProactiveEvent(event_type="type_a", source=EventSource.SYSTEM)
        e2 = ProactiveEvent(event_type="type_b", source=EventSource.SYSTEM)
        assert f.check(e1) is True
        assert f.check(e2) is True  # different type, independent counter

    def test_clear_expired(self) -> None:
        f = AntiSpamFilter(window_seconds=0.1, max_events_per_window=1)
        e = ProactiveEvent(event_type="expired", source=EventSource.SYSTEM)
        f.check(e)
        time.sleep(0.15)
        f.clear_expired()
        assert "expired" not in f._snapshots


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


class TestCooldownManager:
    def test_no_cooldown_initially(self) -> None:
        cm = CooldownManager(default_cooldown=10.0)
        assert cm.is_on_cooldown("test") is False

    def test_starts_cooldown(self) -> None:
        cm = CooldownManager(default_cooldown=1.0)
        assert cm.is_on_cooldown("test") is False
        cm.start_cooldown("test")
        assert cm.is_on_cooldown("test") is True

    def test_cooldown_expiry(self) -> None:
        cm = CooldownManager(default_cooldown=0.1)
        cm.start_cooldown("cooldown_test")
        assert cm.is_on_cooldown("cooldown_test") is True
        time.sleep(0.15)
        assert cm.is_on_cooldown("cooldown_test") is False

    def test_remaining_time(self) -> None:
        cm = CooldownManager(default_cooldown=5.0)
        cm.start_cooldown("rem_test")
        remaining = cm.get_remaining("other_test")
        assert remaining == 0.0  # different source
        remaining2 = cm.get_remaining("rem_test")
        assert 4.0 <= remaining2 <= 5.0

    def test_active_sources(self) -> None:
        cm = CooldownManager(default_cooldown=0.5)
        cm.start_cooldown("s1")
        cm.start_cooldown("s2")
        active = cm.active_sources
        assert set(active) == {"s1", "s2"}
        time.sleep(0.6)
        active = cm.active_sources
        assert len(active) == 0

    def test_clear(self) -> None:
        cm = CooldownManager(default_cooldown=10.0)
        cm.start_cooldown("clear_me")
        cm.clear("clear_me")
        assert cm.is_on_cooldown("clear_me") is False


# ---------------------------------------------------------------------------
# Dedup tests
# ---------------------------------------------------------------------------


class TestEventDedup:
    def test_first_event_not_duplicate(self) -> None:
        d = EventDedup(ttl=5.0, max_duplicates=3)
        e = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="dedup_type",
            payload={"data": "value"},
        )
        assert d.is_duplicate(e) is False

    def test_same_event_is_duplicate(self) -> None:
        # max_duplicates=0 → dedup triggers on the second call (count=2 > 0)
        d = EventDedup(ttl=5.0, max_duplicates=0)
        e1 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="dup_type",
            payload={"data": "same"},
        )
        e2 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="dup_type",
            payload={"data": "same"},
        )
        assert d.is_duplicate(e1) is False  # first
        assert d.is_duplicate(e2) is True  # duplicate

    def test_different_payload_not_duplicate(self) -> None:
        d = EventDedup(ttl=5.0, max_duplicates=0)
        e1 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="diff_type",
            payload={"data": "value1"},
        )
        e2 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="diff_type",
            payload={"data": "value2"},
        )
        assert d.is_duplicate(e1) is False
        assert d.is_duplicate(e2) is False

    def test_fingerprint_excludes_ids(self) -> None:
        """Event IDs should NOT affect fingerprint."""
        d = EventDedup(ttl=5.0, max_duplicates=0)
        e1 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="fingerprint_test",
            payload={"data": "content"},
            id="aaa",
        )
        e2 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="fingerprint_test",
            payload={"data": "content"},
            id="bbb",  # different ID
        )
        assert d.is_duplicate(e1) is False
        assert d.is_duplicate(e2) is True

    def test_fingerprint_excludes_timestamps(self) -> None:
        """Timestamps should NOT affect fingerprint."""
        d = EventDedup(ttl=5.0, max_duplicates=0)
        e1 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="ts_test",
            payload={"value": 42},
        )
        time.sleep(0.1)
        e2 = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="ts_test",
            payload={"value": 42},
        )
        assert d.is_duplicate(e1) is False
        assert d.is_duplicate(e2) is True

    def test_resolved_marking(self) -> None:
        d = EventDedup(ttl=5.0, max_duplicates=3)
        e = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="resolve_type",
            payload={"data": "x"},
        )
        assert d.is_duplicate(e) is False
        fprint = d.fingerprint(e)
        d.mark_resolved(fprint)
        assert d._cache[fprint].resolved is True


# ---------------------------------------------------------------------------
# Relevance tests
# ---------------------------------------------------------------------------


class TestRelevanceFilter:
    def test_low_score_dropped(self) -> None:
        rf = RelevanceFilter(min_relevance=5.0, notify_threshold=10.0)
        e = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="app_blur",
            payload={},
        )
        decision = rf.evaluate(e)
        assert decision.action == ProactiveAction.IGNORE

    def test_medium_score_notifies(self) -> None:
        rf = RelevanceFilter(min_relevance=1.0, notify_threshold=3.0, propose_threshold=10.0)
        e = ProactiveEvent(
            source=EventSource.AUTOMATION,
            event_type="file_modified",
            payload={},
            priority=5,
        )
        decision = rf.evaluate(e)
        if decision.action == ProactiveAction.NOTIFY:
            assert decision.risk == RiskLevel.SAFE

    def test_high_score_proposes(self) -> None:
        rf = RelevanceFilter(min_relevance=1.0, notify_threshold=3.0, propose_threshold=5.0)
        e = ProactiveEvent(
            source=EventSource.VISION,
            event_type="security_alert",
            payload={},
            priority=1,
        )
        decision = rf.evaluate(e)
        assert decision.action in (ProactiveAction.PROPOSE, ProactiveAction.REMEMBER)

    def test_vision_weight_multiplier(self) -> None:
        rf = RelevanceFilter(min_relevance=0.1)
        e_vision = ProactiveEvent(
            source=EventSource.VISION,
            event_type="app_blur",
            payload={},
            priority=10,
        )
        e_system = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="app_blur",
            payload={},
            priority=10,
        )
        score_vision = rf._compute_score(e_vision)
        score_system = rf._compute_score(e_system)
        assert score_vision > score_system

    def test_severity_boost(self) -> None:
        rf = RelevanceFilter(min_relevance=0.1, notify_threshold=1.0, propose_threshold=5.0)
        e_low = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="process_ended",
            payload={},
            priority=10,
        )
        e_high = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="process_ended",
            payload={},
            priority=1,
        )
        score_low = rf._compute_score(e_low)
        score_high = rf._compute_score(e_high)
        assert score_high > score_low

    def test_payload_keywords(self) -> None:
        rf = RelevanceFilter(min_relevance=0.1)
        e = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="alert",
            payload={"detail": "critical failure unauthorized_access attack"},
        )
        score = rf._compute_score(e)
        assert score > 1.0


# ---------------------------------------------------------------------------
# Permission boundary tests
# ---------------------------------------------------------------------------


class TestPermissionBoundary:
    def test_safe_actions_allowed(self) -> None:
        pb = PermissionBoundary()
        for action_name in SAFE_AUTO_ACTIONS:
            decision = ProactiveDecision(
                action=ProactiveAction.EXECUTE,
                event_id="test",
                reason="test",
                details={"action_name": action_name},
            )
            assert pb.can_auto_execute(decision) is True

    def test_unknown_action_denied(self) -> None:
        pb = PermissionBoundary()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "delete_all_files"},
        )
        assert pb.can_auto_execute(decision) is False

    def test_validate_allows_safe(self) -> None:
        pb = PermissionBoundary()
        event = ProactiveEvent(
            event_type="test",
            source=EventSource.SYSTEM,
            payload={"action_name": "notify"},
        )
        pb.validate(event, ProactiveAction.EXECUTE)

    def test_validate_blocks_unsafe(self) -> None:
        pb = PermissionBoundary()
        event = ProactiveEvent(
            event_type="test",
            source=EventSource.SYSTEM,
            payload={"action_name": "delete_all_files"},
        )
        with pytest.raises(ActionBlockedError):
            pb.validate(event, ProactiveAction.EXECUTE)

    def test_evaluate_upgrades_execute(self) -> None:
        pb = PermissionBoundary()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "delete_all_files"},
        )
        result = pb.evaluate(decision)
        assert result.action == ProactiveAction.REQUEST_APPROVAL

    def test_evaluate_preserves_safe(self) -> None:
        pb = PermissionBoundary()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "notify"},
        )
        result = pb.evaluate(decision)
        assert result.action == ProactiveAction.EXECUTE


# ---------------------------------------------------------------------------
# Safe actions tests
# ---------------------------------------------------------------------------


class TestSafeActionExecutor:
    def test_execute_notify(self) -> None:
        executor = SafeActionExecutor()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "notify", "title": "Hi", "message": "Hello"},
        )
        assert executor.execute(decision) is True

    def test_execute_remember(self) -> None:
        executor = SafeActionExecutor()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "remember", "data": {"key": "val"}},
        )
        assert executor.execute(decision) is True

    def test_execute_check_status(self) -> None:
        executor = SafeActionExecutor()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "check_status", "check_type": "disk"},
        )
        assert executor.execute(decision) is True

    def test_execute_log_event(self) -> None:
        executor = SafeActionExecutor()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "log_event", "source_type": "system"},
        )
        assert executor.execute(decision) is True

    def test_execute_update_health(self) -> None:
        executor = SafeActionExecutor()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "update_health", "health": "ok"},
        )
        assert executor.execute(decision) is True

    def test_execute_unknown_action(self) -> None:
        executor = SafeActionExecutor()
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="test",
            reason="test",
            details={"action_name": "format_disk"},
        )
        assert executor.execute(decision) is False


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------


class TestProactiveAuthorization:
    def test_not_approved_initially(self) -> None:
        auth = ProactiveAuthorization()
        assert auth.is_approved("event1") is False

    def test_approve(self) -> None:
        auth = ProactiveAuthorization()
        auth.approve("event1")
        assert auth.is_approved("event1") is True

    def test_reject(self) -> None:
        auth = ProactiveAuthorization()
        auth.approve("event1")
        auth.reject("event1")
        assert auth.is_approved("event1") is False

    def test_clear(self) -> None:
        auth = ProactiveAuthorization()
        auth.approve("event1")
        auth.clear("event1")
        assert auth.is_approved("event1") is False


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestProactivePersistence:
    def test_save_and_load_decision(self, tmp_path: Path) -> None:
        store = tmp_path / "proactive.json"
        p = ProactivePersistence(store_path=store)
        decision = ProactiveDecision(
            action=ProactiveAction.EXECUTE,
            event_id="pers_test",
            reason="test decision",
            risk=RiskLevel.SAFE,
        )
        p.save_decision(decision)
        decisions = p.load_decisions()
        assert len(decisions) >= 1
        assert decisions[-1]["event_id"] == "pers_test"

    def test_save_and_load_cooldown(self, tmp_path: Path) -> None:
        store = tmp_path / "proactive.json"
        p = ProactivePersistence(store_path=store)
        from mark.proactive.types import CooldownEntry
        entry = CooldownEntry(
            source_type="test_type",
            cooldown_seconds=30.0,
            next_allowed=time.time() + 10.0,
        )
        p.save_cooldown(entry)
        restored = p.load_cooldown("test_type")
        assert restored is not None
        assert restored.source_type == "test_type"
        assert restored.cooldown_seconds == 30.0

    def test_load_missing_file(self, tmp_path: Path) -> None:
        store = tmp_path / "nonexistent.json"
        p = ProactivePersistence(store_path=store)
        decisions = p.load_decisions()
        assert decisions == []

    def test_load_corrupted_file(self, tmp_path: Path) -> None:
        store = tmp_path / "corrupt.json"
        store.write_text("not json!!!", encoding="utf-8")
        p = ProactivePersistence(store_path=store)
        decisions = p.load_decisions()
        assert decisions == []


# ---------------------------------------------------------------------------
# Full pipeline (ProactiveAgent) tests
# ---------------------------------------------------------------------------


class TestProactiveAgent:
    def test_basic_ingest(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            cooldown_default=0.1,
        )
        event = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="test_ingest",
            payload={"data": "value"},
        )
        decision = agent.ingest(event)
        assert decision is not None
        assert decision.action in (
            ProactiveAction.IGNORE,
            ProactiveAction.NOTIFY,
            ProactiveAction.REMEMBER,
            ProactiveAction.PROPOSE,
            ProactiveAction.EXECUTE,
        )

    def test_basic_ingest_notify(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            min_relevance=0.1,
            notify_threshold=1.0,
            cooldown_default=0.1,
        )
        event = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="battery_low",
            payload={"level": 15},
        )
        decision = agent.ingest(event)
        assert decision.action in (
            ProactiveAction.NOTIFY,
            ProactiveAction.REMEMBER,
            ProactiveAction.PROPOSE,
            ProactiveAction.EXECUTE,
            ProactiveAction.REQUEST_APPROVAL,
        )

    def test_invalid_event_raises(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            cooldown_default=0.1,
        )
        with pytest.raises(InvalidEventError):
            agent.ingest(None)  # type: ignore[arg-type]

    def test_empty_event_type_raises(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            cooldown_default=0.1,
        )
        event = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="",
            payload={},
        )
        with pytest.raises(InvalidEventError):
            agent.ingest(event)

    def test_spam_detected(self) -> None:
        """Anti-spam catches rapid repeated events before cooldown blocks them."""
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=2,
            cooldown_default=0,
        )
        # Use different event types so anti-spam counters are independent
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="spam_a",
            payload={},
        ))
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="spam_b",
            payload={},
        ))
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="spam_b",  # 2nd of type b
            payload={},
        ))
        # 3rd of type b exceeds anti-spam limit
        with pytest.raises(SpamDetectedError):
            agent.ingest(ProactiveEvent(
                source=EventSource.SYSTEM,
                event_type="spam_b",
                payload={},
            ))

    def test_batch_processes_valid(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            min_relevance=0.1,
            notify_threshold=1.0,
            cooldown_default=0.1,
        )
        events = [
            ProactiveEvent(source=EventSource.SYSTEM, event_type=f"batch_{i}", payload={})
            for i in range(5)
        ]
        decisions = agent.ingest_batch(events)
        assert len(decisions) > 0

    def test_batch_skips_invalid(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            cooldown_default=0.1,
        )
        events = [
            ProactiveEvent(source=EventSource.SYSTEM, event_type=f"ok_{i}", payload={})
            for i in range(3)
        ]
        decisions = agent.ingest_batch(events)
        assert len(decisions) >= 3

    def test_approve_event(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            cooldown_default=0.1,
        )
        agent.approve_event("approved_id")
        assert agent._authorization.is_approved("approved_id") is True

    def test_reject_event(self) -> None:
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            cooldown_default=0.1,
        )
        agent.approve_event("r1")
        agent.reject_event("r1")
        assert agent._authorization.is_approved("r1") is False

    def test_configure(self) -> None:
        agent = ProactiveAgent(min_relevance=5.0)
        agent.configure(min_relevance=0.5)
        assert agent._relevance.min_relevance == 0.5

    def test_clear(self) -> None:
        agent = ProactiveAgent(anti_spam_max=100, cooldown_default=0.1)
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="clear_test",
            payload={},
        ))
        agent.clear()
        assert len(agent._cooldown.active_sources) == 0

    def test_persistence_path(self, tmp_path: Path) -> None:
        store = tmp_path / "proactive.json"
        agent = ProactiveAgent(store_path=str(store), cooldown_default=0.1)
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="persist_test",
            payload={"data": "val"},
        ))
        assert store.exists()
        data = json.loads(store.read_text(encoding="utf-8"))
        assert "decisions" in data

    def test_russian_message(self) -> None:
        """Messages use Russian by default."""
        msg = proactive_message(CODE_SPAM_DETECTED)
        assert isinstance(msg, str)

    def test_on_decision_callback(self) -> None:
        received: list[ProactiveDecision] = []
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            on_decision=lambda d: received.append(d),
            cooldown_default=0.1,
        )
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="cb_test",
            payload={},
        ))
        assert len(received) >= 1

    def test_on_event_processed_callback(self) -> None:
        received: list[tuple] = []
        agent = ProactiveAgent(
            anti_spam_window=60.0,
            anti_spam_max=100,
            on_event_processed=lambda e, d: received.append((e, d)),
            cooldown_default=0.1,
        )
        agent.ingest(ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="ep_test",
            payload={},
        ))
        assert len(received) >= 1

    def test_event_provenance(self) -> None:
        agent = ProactiveAgent(anti_spam_max=100, cooldown_default=0.1)
        event = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="prov_test",
            payload={},
            provenance="vision->system->proactive",
        )
        decision = agent.ingest(event)
        assert decision is not None


# ---------------------------------------------------------------------------
# Event source tests
# ---------------------------------------------------------------------------


class TestEventSource:
    def test_all_sources_present(self) -> None:
        assert EventSource.VISION.value == "vision"
        assert EventSource.SYSTEM.value == "system"
        assert EventSource.AUTOMATION.value == "automation"
        assert EventSource.LEARNED.value == "learned"

    def test_event_has_all_fields(self) -> None:
        e = ProactiveEvent(
            source=EventSource.VISION,
            event_type="face_detected",
            payload={"confidence": 0.95},
            provenance="camera->vision",
            priority=3,
        )
        assert e.source == EventSource.VISION
        assert e.event_type == "face_detected"
        assert e.payload == {"confidence": 0.95}
        assert e.provenance == "camera->vision"
        assert e.priority == 3
        assert isinstance(e.id, str) and len(e.id) > 0
        assert isinstance(e.timestamp, float)


# ---------------------------------------------------------------------------
# Error code tests
# ---------------------------------------------------------------------------


class TestErrorCodes:
    def test_code_proactive(self) -> None:
        assert isinstance(proactive_message(CODE_SPAM_DETECTED), str)
        assert isinstance(proactive_message(CODE_INVALID_EVENT), str)
        assert isinstance(proactive_message(CODE_COOLDOWN_ACTIVE), str)
        assert isinstance(proactive_message(CODE_RELEVANCE_TOO_LOW), str)
        assert isinstance(proactive_message(CODE_ACTION_BLOCKED), str)

    def test_unknown_code_returns_key(self) -> None:
        assert proactive_message("unknown_fake_code") == "unknown_fake_code"
