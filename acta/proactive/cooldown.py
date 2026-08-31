"""Cooldown manager: prevents the proactive agent from acting too frequently.

Per-source cooldown ensures the same event source_type cannot trigger
proactive decisions more than once per cooldown window.
"""
from __future__ import annotations

import time
from collections import defaultdict

from acta.proactive.errors import (
    CODE_COOLDOWN_ACTIVE,
    CooldownActiveError,
)
from acta.proactive.types import CooldownEntry


class CooldownManager:
    """Per-source cooldown enforcement.

    Each source_type gets an independent timer.
    """

    def __init__(self, default_cooldown: float = 30.0) -> None:
        self._default_cooldown = default_cooldown
        self._entries: dict[str, CooldownEntry] = {}

    def is_on_cooldown(self, source_type: str) -> bool:
        """Return True if this source_type is still cooling down."""
        entry = self._entries.get(source_type)
        if entry is None:
            return False
        now = time.time()
        if now < entry.next_allowed:
            return True
        entry.next_allowed = now  # reset
        return False

    def start_cooldown(self, source_type: str) -> float:
        """Start (or extend) the cooldown for source_type.

        Returns the next_allowed timestamp.
        """
        entry = self._entries.get(source_type)
        if entry is None:
            entry = CooldownEntry(
                source_type=source_type,
                cooldown_seconds=self._default_cooldown,
            )
            self._entries[source_type] = entry
        else:
            entry.cooldown_seconds = self._default_cooldown

        now = time.time()
        entry.next_allowed = now + entry.cooldown_seconds
        return entry.next_allowed

    def get_remaining(self, source_type: str, now: float | None = None) -> float:
        """Seconds remaining on cooldown, or 0.0 if not active."""
        now = now or time.time()
        entry = self._entries.get(source_type)
        if entry is None:
            return 0.0
        remaining = entry.next_allowed - now
        return max(0.0, remaining)

    def clear(self, source_type: str) -> None:
        """Remove the entry (e.g. after approval or manual reset)."""
        self._entries.pop(source_type, None)

    @property
    def default_cooldown(self) -> float:
        return self._default_cooldown

    @property
    def active_sources(self) -> list[str]:
        """Source types still on cooldown."""
        now = time.time()
        return [
            st for st, e in self._entries.items()
            if now < e.next_allowed
        ]
