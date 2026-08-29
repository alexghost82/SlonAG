"""Deduplication manager — prevents duplicate event processing.

Tracks recently seen events within a sliding window and suppresses
re-processing of events with the same (source, event_type, fingerprint).
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DedupKey:
    """A deduplication key derived from event content."""

    source: str
    event_type: str
    fingerprint: str          # content hash (e.g. body, message)
    key: str = field(default="")
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.key:
            object.__setattr__(self, "key", DedupManager.fingerprint(
                self.source, self.event_type, self.fingerprint
            ))
        if self.created_at == 0.0:
            object.__setattr__(self, "created_at", time.time())


class DedupManager:
    """Sliding-window deduplication.

    Events with the same (source, event_type, fingerprint) within
    ``window_seconds`` are considered duplicates and suppressed.
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        self._window = window_seconds
        self._seen: deque[DedupKey] = deque()
        self._set: set[str] = set()  # for O(1) lookup

    @staticmethod
    def fingerprint(source: str, event_type: str, content: str) -> str:
        raw = f"{source}:{event_type}:{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_duplicate(self, dedup_key: DedupKey) -> bool:
        """Return True if this event is a duplicate within the window."""
        self._cleanup()
        if dedup_key.key in self._set:
            return True

        self._set.add(dedup_key.key)
        self._seen.append(dedup_key)
        return False

    def _cleanup(self) -> None:
        now = time.time()
        cutoff = now - self._window
        while self._seen and self._seen[0].created_at < cutoff:
            removed = self._seen.popleft()
            self._set.discard(removed.key)

    def add(self, key: str) -> bool:
        """Add a raw dedup key string. Returns True if it was new."""
        self._cleanup()
        if key in self._set:
            return False  # duplicate
        now = time.time()
        self._set.add(key)
        self._seen.append(DedupKey(
            source="", event_type="", fingerprint="",
            created_at=now, key=key,
        ))
        return True

    @property
    def active_count(self) -> int:
        return len(self._set)

    @property
    def window_seconds(self) -> float:
        return self._window

    def set_window(self, window_seconds: float) -> None:
        self._window = window_seconds

    def reset(self) -> None:
        self._set.clear()
        self._seen.clear()
