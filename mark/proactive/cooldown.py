"""Cooldown manager — prevents repeated events within a time window.

Ensures the proactive agent does not spam the user with the same or
similar events within ``cooldown_seconds``.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class CooldownEntry:
    """Single cooldown entry: key + last firing time."""

    key: str
    last_fired_at: float


class CooldownManager:
    """Thread-safe (single-thread assumed) cooldown tracker.

    Uses a sliding-window approach: after an event fires, the same key
    cannot fire again until ``duration`` seconds have elapsed.
    """

    def __init__(self, default_duration: float = 60.0) -> None:
        self._entries: dict[str, CooldownEntry] = {}
        self._default_duration = default_duration
        self._per_key_durations: dict[str, float] = {}

    def is_cooldown_active(self, key: str) -> bool:
        """Return True if ``key`` is still within its cooldown window."""
        entry = self._entries.get(key)
        if entry is None:
            return False
        duration = self._per_key_durations.get(key, self._default_duration)
        elapsed = time.time() - entry.last_fired_at
        return elapsed < duration

    def fire(self, key: str) -> float:
        """Mark ``key`` as fired, return the timestamp (now)."""
        self._entries[key] = CooldownEntry(
            key=key,
            last_fired_at=time.time(),
        )
        return self._entries[key].last_fired_at

    def set_duration(self, key: str, duration: float) -> None:
        """Override cooldown duration for a specific key."""
        self._per_key_durations[key] = duration

    def time_remaining(self, key: str) -> float:
        """Seconds remaining in cooldown for ``key``. 0 if not active."""
        entry = self._entries.get(key)
        if entry is None:
            return 0.0
        duration = self._per_key_durations.get(key, self._default_duration)
        elapsed = time.time() - entry.last_fired_at
        return max(0.0, duration - elapsed)

    def cleanup(self) -> int:
        """Remove entries that have fully expired. Return count removed."""
        now = time.time()
        expired = [
            k for k, v in self._entries.items()
            if now - v.last_fired_at >= self._per_key_durations.get(k, self._default_duration)
        ]
        for k in expired:
            del self._entries[k]
        return len(expired)

    def reset(self) -> None:
        """Clear all cooldown state."""
        self._entries.clear()
        self._per_key_durations.clear()

    @property
    def active_count(self) -> int:
        return len(self._entries)
