"""Tests for mark.proactive.dedup.DedupManager."""

from __future__ import annotations

import time
import pytest

from mark.proactive.dedup import DedupManager, DedupKey


class TestDedupKey:
    def test_fingerprint(self) -> None:
        fp = DedupManager.fingerprint("vision", "motion", "same content")
        assert len(fp) == 16
        assert isinstance(fp, str)

    def test_same_content_same_fingerprint(self) -> None:
        fp1 = DedupManager.fingerprint("vision", "motion", "same content")
        fp2 = DedupManager.fingerprint("vision", "motion", "same content")
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self) -> None:
        fp1 = DedupManager.fingerprint("vision", "motion", "content A")
        fp2 = DedupManager.fingerprint("vision", "motion", "content B")
        assert fp1 != fp2

    def test_different_source_different_fingerprint(self) -> None:
        fp1 = DedupManager.fingerprint("vision", "motion", "same")
        fp2 = DedupManager.fingerprint("system", "motion", "same")
        assert fp1 != fp2


class TestDedupManager:
    def test_first_event_not_duplicate(self) -> None:
        m = DedupManager(window_seconds=300.0)
        key = DedupKey(source="vision", event_type="motion", fingerprint="abc")
        assert m.is_duplicate(key) is False

    def test_same_key_is_duplicate(self) -> None:
        m = DedupManager(window_seconds=300.0)
        key = DedupKey(source="vision", event_type="motion", fingerprint="abc")
        assert m.is_duplicate(key) is False
        assert m.is_duplicate(key) is True

    def test_different_keys_not_duplicate(self) -> None:
        m = DedupManager(window_seconds=300.0)
        key1 = DedupKey(source="vision", event_type="motion", fingerprint="abc")
        key2 = DedupKey(source="vision", event_type="motion", fingerprint="def")
        assert m.is_duplicate(key1) is False
        assert m.is_duplicate(key2) is False

    def test_cleanup_expired(self) -> None:
        m = DedupManager(window_seconds=0.001)
        key = DedupKey(source="vision", event_type="motion", fingerprint="abc")
        assert m.is_duplicate(key) is False
        time.sleep(0.01)
        # After cleanup, the key should expire
        m._cleanup()
        assert m.active_count == 0

    def test_active_count(self) -> None:
        m = DedupManager(window_seconds=300.0)
        assert m.active_count == 0
        key1 = DedupKey(source="vision", event_type="motion", fingerprint="a")
        key2 = DedupKey(source="vision", event_type="motion", fingerprint="b")
        m.is_duplicate(key1)
        m.is_duplicate(key2)
        assert m.active_count == 2

    def test_reset(self) -> None:
        m = DedupManager(window_seconds=300.0)
        key = DedupKey(source="vision", event_type="motion", fingerprint="abc")
        m.is_duplicate(key)
        assert m.active_count == 1
        m.reset()
        assert m.active_count == 0

    def test_add_raw_key(self) -> None:
        m = DedupManager(window_seconds=300.0)
        key_str = "vision:motion:abc"
        assert m.add(key_str) is True  # new
        assert m.add(key_str) is False  # duplicate
