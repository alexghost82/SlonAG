"""Event deduplication by content fingerprint.

Normalizes event content (ignoring timestamps, IDs, noise) and
hashes the result. Near-duplicates within a short window are
collapsed into a single decision.
"""
from __future__ import annotations

import hashlib
import json
import time

from acta.proactive.types import DedupState, ProactiveEvent

# How long a fingerprint is considered "active" before it's
# pruned from the dedup cache.
_DEFAULT_FINGERPRINT_TTL: float = 300.0  # 5 minutes


class EventDedup:
    """Fingerprint-based dedup for proactive events."""

    def __init__(
        self,
        ttl: float = _DEFAULT_FINGERPRINT_TTL,
        max_duplicates: int = 3,
    ) -> None:
        self._ttl = ttl
        self._max_duplicates = max_duplicates
        self._cache: dict[str, DedupState] = {}

    def fingerprint(self, event: ProactiveEvent) -> str:
        """Create a content-based fingerprint for an event."""
        # Normalize: strip IDs, normalize keys, ignore noise
        normalized = {
            "source": event.source,
            "event_type": event.event_type,
            "payload": _normalize_payload(event.payload),
        }
        raw = json.dumps(normalized, sort_keys=True, default=_json_default)
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_duplicate(self, event: ProactiveEvent) -> bool:
        """Return True if the event is a known duplicate within TTL."""
        fprint = self.fingerprint(event)
        now = time.time()

        existing = self._cache.get(fprint)
        if existing is None:
            self._cache[fprint] = DedupState(
                fingerprint=fprint,
                last_seen_at=now,
                count=1,
            )
            return False

        # Expired
        if now - existing.last_seen_at > self._ttl:
            existing.last_seen_at = now
            existing.count = 1
            existing.resolved = False
            return False

        existing.count += 1
        existing.last_seen_at = now

        if existing.count > self._max_duplicates:
            return True

        return False

    def mark_resolved(self, fingerprint: str) -> None:
        """Mark a fingerprint as resolved (user handled the duplicate)."""
        entry = self._cache.get(fingerprint)
        if entry:
            entry.resolved = True

    def clear_expired(self, now: float | None = None) -> None:
        """Remove fingerprints older than TTL."""
        now = now or time.time()
        expired = [
            fp for fp, ds in self._cache.items()
            if now - ds.last_seen_at > self._ttl
        ]
        for fp in expired:
            del self._cache[fp]

    @property
    def cache_size(self) -> int:
        return len(self._cache)


def _json_default(obj: object) -> object:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    return str(obj)


def _normalize_payload(payload: dict) -> dict:
    """Remove noise fields from payload for fingerprinting."""
    cleaned: dict = {}
    for k, v in payload.items():
        key = str(k).lower().strip()
        # Skip timing/noise fields
        if key in ("id", "timestamp", "epoch", "ts", "time"):
            continue
        if isinstance(v, str) and len(v) > 200:
            v = v[:200] + "..."
        cleaned[key] = v
    return cleaned
