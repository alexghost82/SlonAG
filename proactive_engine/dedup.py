"""Deduplication for proactive triggers.

Maps trigger attributes to a hash key so that repeated events
from the same source within a time window are collapsed.
"""

from __future__ import annotations

import hashlib
import time
import threading
from typing import Any

from proactive_engine.types import ProactiveTrigger


class TriggerDeduper:
    """Deduplicates near-duplicate triggers by hashing a key."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._keys: dict[str, float] = {}
        self._lock = threading.Lock()

    def compute_key(self, trigger: ProactiveTrigger) -> str:
        """Produce a deterministic dedup key from trigger attributes."""
        payload_str = ""
        if trigger.payload:
            items = sorted(trigger.payload.items())
            payload_str = "|".join(f"{k}={v}" for k, v in items)
        raw = f"{trigger.source.value}:{trigger.event_type}:{payload_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_deduped(self, trigger: ProactiveTrigger) -> tuple[bool, str]:
        """Return (is_deduped, reason)."""
        key = self.compute_key(trigger)
        now = time.time()
        with self._lock:
            expired = [
                k for k, ts in self._keys.items()
                if now - ts > self._window
            ]
            for k in expired:
                del self._keys[k]

            if key in self._keys:
                return True, f"duplicate within {self._window}s (key={key})"

            self._keys[key] = now
            return False, ""

    def clear(self) -> int:
        with self._lock:
            count = len(self._keys)
            self._keys.clear()
            return count
