"""Cooldown / rate limiting for proactive triggers.

Supports per-trigger-type cooldown windows and global rate limits.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class TriggerCooldown:
    """Enforces a minimum time between events of the same type."""

    def __init__(self, default_cooldown: float = 300.0) -> None:
        self._default = default_cooldown
        self._overrides: dict[str, float] = {}
        self._last_fired: dict[str, float] = {}
        self._lock = threading.Lock()

    def set_cooldown(self, event_type: str, seconds: float) -> None:
        self._overrides[event_type] = seconds

    def effective_cooldown(self, event_type: str) -> float:
        return self._overrides.get(event_type, self._default)

    def allow(self, event_type: str) -> tuple[bool, float]:
        """Return (allowed, remaining_cooldown_seconds)."""
        now = time.time()
        cooldown = self.effective_cooldown(event_type)
        with self._lock:
            last = self._last_fired.get(event_type, 0.0)
            if now - last < cooldown:
                remaining = cooldown - (now - last)
                return False, remaining
            self._last_fired[event_type] = now
            return True, 0.0


class EventRateLimiter:
    """Rate-limits events from the same event_type using a sliding window."""

    def __init__(self, max_per_minute: int = 10) -> None:
        self._max_per_minute = max_per_minute
        self._timestamps: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, event_type: str) -> bool:
        """Return True if the event_type may proceed within the rate limit."""
        now = time.time()
        with self._lock:
            if event_type not in self._timestamps:
                self._timestamps[event_type] = deque()

            dq = self._timestamps[event_type]
            while dq and now - dq[0] > 60.0:
                dq.popleft()

            if len(dq) >= self._max_per_minute:
                return False

            dq.append(now)
            return True
