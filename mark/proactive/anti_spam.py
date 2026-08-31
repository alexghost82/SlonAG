"""Anti-spam sliding-window deduplication layer.

Monitors event frequencies per source_type within a configurable
time window. Events exceeding the rate limit are silently dropped
before reaching the relevance filter or downstream action.
"""
from __future__ import annotations

import time
from collections import defaultdict

from mark.proactive.errors import (
    CODE_SPAM_DETECTED,
    ProactiveError,
    SpamDetectedError,
)
from mark.proactive.types import AntiSpamSnapshot, ProactiveEvent


class AntiSpamFilter:
    """Sliding-window anti-spam filter.

    Each event type has an independent counter that resets after
    the configured window expires.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        max_events_per_window: int = 10,
    ) -> None:
        self._window = window_seconds
        self._max = max_events_per_window
        self._snapshots: dict[str, AntiSpamSnapshot] = {}

    def _get_or_create(self, event_type: str) -> AntiSpamSnapshot:
        snap = self._snapshots.get(event_type)
        if snap is None:
            snap = AntiSpamSnapshot(
                type=event_type,
                window_seconds=self._window,
                max_count=self._max,
            )
            self._snapshots[event_type] = snap
        return snap

    def check(self, event: ProactiveEvent) -> bool:
        """Return True if event is allowed, False if it's spam."""
        now = time.time()
        snap = self._get_or_create(event.event_type)

        # Prune old timestamps
        cutoff = now - snap.window_seconds
        snap.timestamps = [t for t in snap.timestamps if t > cutoff]

        if len(snap.timestamps) >= snap.max_count:
            return False  # SPAM

        snap.timestamps.append(now)
        return True

    def clear_expired(self, now: float | None = None) -> None:
        """Remove snapshots with zero timestamps."""
        now = now or time.time()
        expired = [
            et for et, s in self._snapshots.items()
            if not s.timestamps or all(t < now - s.window_seconds for t in s.timestamps)
        ]
        for et in expired:
            del self._snapshots[et]

    @property
    def window_seconds(self) -> float:
        return self._window

    @property
    def max_events_per_window(self) -> int:
        return self._max
