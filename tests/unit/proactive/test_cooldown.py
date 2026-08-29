"""Tests for mark.proactive.cooldown.CooldownManager."""

from __future__ import annotations

import time
import pytest

from mark.proactive.cooldown import CooldownManager


class TestCooldownManager:
    def test_initial_state(self) -> None:
        m = CooldownManager(default_duration=60.0)
        assert m.is_cooldown_active("key1") is False
        assert m.time_remaining("key1") == 0.0

    def test_fire_activates(self) -> None:
        m = CooldownManager(default_duration=60.0)
        timestamp = m.fire("key1")
        assert timestamp > 0
        assert m.is_cooldown_active("key1") is True
        remaining = m.time_remaining("key1")
        assert 59.0 <= remaining <= 60.0

    def test_different_keys_independent(self) -> None:
        m = CooldownManager(default_duration=60.0)
        m.fire("key1")
        assert m.is_cooldown_active("key1") is True
        assert m.is_cooldown_active("key2") is False

    def test_cleanup_removes_expired(self) -> None:
        m = CooldownManager(default_duration=0.001)
        m.fire("key1")
        time.sleep(0.01)
        removed = m.cleanup()
        assert removed >= 1
        assert m.is_cooldown_active("key1") is False

    def test_active_count(self) -> None:
        m = CooldownManager(default_duration=60.0)
        assert m.active_count == 0
        m.fire("key1")
        m.fire("key2")
        assert m.active_count == 2

    def test_set_duration(self) -> None:
        m = CooldownManager(default_duration=60.0)
        m.set_duration("special", 120.0)
        m.fire("special")
        remaining = m.time_remaining("special")
        assert 119.0 <= remaining <= 120.0

    def test_reset(self) -> None:
        m = CooldownManager(default_duration=60.0)
        m.fire("key1")
        assert m.is_cooldown_active("key1") is True
        m.reset()
        assert m.is_cooldown_active("key1") is False
