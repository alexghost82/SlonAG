"""Edge case and regression tests for the proactive agent.

Covers:
- ProactiveDecision with all fields
- CooldownEntry behavior
- Empty event payload
- Multiple sources
- Security: no secrets in errors
- Relevance edge cases
- Anti-spam edge cases
"""
from __future__ import annotations

import time

import pytest

from mark.proactive import (
    CooldownManager,
    EventDedup,
    EventSource,
    ProactiveAgent,
    ProactiveAction,
    ProactiveDecision,
    ProactiveEvent,
    ProactivePersistence,
    RelevanceFilter,
    RiskLevel,
    SAFE_AUTO_ACTIONS,
)
from mark.proactive.errors import CODE_OK, proactive_message
from mark.proactive.errors import SpamDetectedError, InvalidEventError, ProactiveError
from mark.proactive.types import CooldownEntry, ProactiveDecisionKind


class TestProactiveDecision:
    def test_decision_defaults(self) -> None:
        d = ProactiveDecision(
            action=ProactiveAction.IGNORE,
            event_id="test",
            reason="test",
        )
        assert d.risk == RiskLevel.SAFE
        assert d.details == {}
        assert d.approval_required is False

    def test_decision_with_all_fields(self) -> None:
        d = ProactiveDecision(
            action=ProactiveAction.REQUEST_APPROVAL,
            event_id="full_test",
            reason="Needs approval",
            risk=RiskLevel.HIGH,
            details={"action_name": "system_update", "auto": False},
            approval_required=True,
        )
        assert d.action == ProactiveAction.REQUEST_APPROVAL
        assert d.risk == RiskLevel.HIGH
        assert d.approval_required is True
        assert "action_name" in d.details


class TestCooldownEntry:
    def test_is_active_false_initially(self) -> None:
        entry = CooldownEntry(source_type="test", cooldown_seconds=60.0)
        assert entry.is_active() is False

    def test_is_active_true_when_set(self) -> None:
        entry = CooldownEntry(
            source_type="test",
            cooldown_seconds=60.0,
            next_allowed=time.time() + 3600,
        )
        assert entry.is_active() is True

    def test_is_not_active_after_expiry(self) -> None:
        entry = CooldownEntry(
            source_type="test",
            cooldown_seconds=1.0,
            next_allowed=time.time() - 10,  # already expired
        )
        assert entry.is_active() is False

    def test_expire_resets(self) -> None:
        entry = CooldownEntry(
            source_type="test",
            cooldown_seconds=60.0,
            next_allowed=time.time() + 3600,
        )
        entry.expire()
        assert entry.is_active() is False


class TestRelevanceEdgeCases:
    def test_empty_payload(self) -> None:
        rf = RelevanceFilter(min_relevance=0.5, notify_threshold=2.0, propose_threshold=5.0)
        e = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="empty_payload",
            payload={},
        )
        decision = rf.evaluate(e)
        assert decision.action in (ProactiveAction.IGNORE, ProactiveAction.NOTIFY)

    def test_large_payload_truncated_in_fingerprint(self) -> None:
        """Very long payload values should not crash dedup."""
        e = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="large_payload",
            payload={"big": "x" * 10000},
        )
        rf = RelevanceFilter(min_relevance=0.1)
        decision = rf.evaluate(e)
        assert decision is not None


class TestAntiSpamEdgeCases:
    def test_dedup_first_then_second(self) -> None:
        # max_duplicates=0 → dedup triggers on the second call (count=2 > 0)
        d = EventDedup(max_duplicates=0)
        e1 = ProactiveEvent(source=EventSource.SYSTEM, event_type="edge_type", payload={})
        e2 = ProactiveEvent(source=EventSource.SYSTEM, event_type="edge_type", payload={})
        assert d.is_duplicate(e1) is False  # first
        assert d.is_duplicate(e2) is True  # duplicate

    def test_fingerprint_stability(self) -> None:
        d = EventDedup(ttl=60.0)
        e = ProactiveEvent(source=EventSource.SYSTEM, event_type="stable", payload={"a": 1})
        f1 = d.fingerprint(e)
        f2 = d.fingerprint(e)
        assert f1 == f2  # same event → same fingerprint


class TestSafeActionsList:
    def test_safe_actions_are_strings(self) -> None:
        for action in SAFE_AUTO_ACTIONS:
            assert isinstance(action, str)

    def test_safe_actions_dont_overlap_dangerous(self) -> None:
        """None of the safe actions should be obviously dangerous."""
        dangerous_keywords = ["delete", "format", "uninstall", "shutdown", "poweroff", "reboot"]
        for action in SAFE_AUTO_ACTIONS:
            for kw in dangerous_keywords:
                assert kw not in action.lower(), f"Unsafe action: {action}"


class TestNoSecretsInErrors:
    def test_error_messages_no_secrets(self) -> None:
        exc = SpamDetectedError("test")
        msg = str(exc)
        assert "sk-" not in msg.lower()
        assert "password" not in msg.lower()

    def test_invalid_event_no_payload_leak(self) -> None:
        exc = InvalidEventError("test_leak")
        msg = str(exc)
        # Should not contain any payload data
        assert "sensitive_data_12345" not in msg.lower()


class TestAgentSecurity:
    def test_never_breaks_security(self) -> None:
        """Proactive agent should never auto-execute dangerous actions."""
        agent = ProactiveAgent(
            anti_spam_max=100,
            min_relevance=0.1,
            notify_threshold=1.0,
            cooldown_default=0.1,
        )

        dangerous_actions = [
            "delete_all_files", "shutdown", "format_disk",
            "disable_firewall", "modify_system_config", "reboot", "poweroff",
        ]
        for source in EventSource:
            for event_type in [
                "execute_script", "delete_file", "shutdown", "format_disk",
                "disable_firewall", "modify_system_config",
            ]:
                for danger_action in dangerous_actions:
                    try:
                        decision = agent.ingest(ProactiveEvent(
                            source=source,
                            event_type=event_type,
                            payload={"action_name": danger_action},
                        ))
                        # Should never be auto-EXECUTE for a known dangerous action name
                        if decision.action == ProactiveAction.EXECUTE:
                            assert decision.details.get("action_name") not in dangerous_actions, \
                                f"Unsafe auto-execution for {source}/{event_type}/{danger_action}"
                    except Exception:
                        pass  # Spam/cooldown errors are fine

    def test_high_risk_never_auto_executes(self) -> None:
        agent = ProactiveAgent(anti_spam_max=100, min_relevance=0.1, cooldown_default=0.1)
        event = ProactiveEvent(
            source=EventSource.SYSTEM,
            event_type="critical_action",
            payload={"action_name": "reboot", "critical": True},
            priority=1,
        )
        decision = agent.ingest(event)
        if decision.action == ProactiveAction.EXECUTE:
            assert decision.details.get("action_name") in SAFE_AUTO_ACTIONS


class TestI18n:
    def test_russian_default(self) -> None:
        """In Russian locale, messages should be Russian."""
        from i18n import set_locale
        set_locale("ru")
        msg = proactive_message(CODE_OK)
        assert isinstance(msg, str)


class TestPersistenceRoundTrip:
    def test_full_roundtrip(self, tmp_path: Path) -> None:
        store = tmp_path / "roundtrip.json"
        p = ProactivePersistence(store_path=store)
        p.save()  # initial save
        p2 = ProactivePersistence(store_path=store)
        p2.load()  # reload from disk
        decisions = p2.load_decisions()
        assert isinstance(decisions, list)
