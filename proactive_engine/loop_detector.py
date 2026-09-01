"""Loop detection — prevent infinite self-trigger cycles.

Tracks chains of related triggers (same source → same event_type
or related event_types). If a chain exceeds max_loop_count,
further triggers are blocked with LOOP_BLOCKED.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerChain:
    """Tracks a chain of related trigger activations."""

    source: str
    event_type: str
    chain_id: str  # hash of source+event_type pair
    activations: list[float] = field(default_factory=list)
    last_reset: float = field(default_factory=time.time)
    chain_window: float = 300.0  # 5 minutes

    @property
    def count(self) -> int:
        now = time.time()
        # Prune old activations
        cutoff = now - self.chain_window
        self.activations = [t for t in self.activations if t > cutoff]
        return len(self.activations)

    def add_activation(self) -> int:
        self.activations.append(time.time())
        return self.count


class LoopDetector:
    """Detects and prevents infinite self-trigger loops.

    A loop occurs when the same trigger source + event_type fires
    repeatedly as a result of a previous proactive execution.
    """

    def __init__(self, max_loop_count: int = 3) -> None:
        self._max_loop_count = max_loop_count
        self._chains: dict[str, TriggerChain] = {}
        self._lock = threading.Lock()

    def check(self, source: str, event_type: str) -> tuple[bool, int]:
        """Return (allowed, current_chain_count).

        If blocked, current_chain_count == the count at max.
        """
        chain_id = f"{source}:{event_type}"
        with self._lock:
            if chain_id not in self._chains:
                self._chains[chain_id] = TriggerChain(
                    source=source,
                    event_type=event_type,
                    chain_id=chain_id,
                )

            chain = self._chains[chain_id]
            count = chain.count
            if count >= self._max_loop_count:
                return False, count

            new_count = chain.add_activation()
            return True, new_count

    def record_completion(self, source: str, event_type: str) -> None:
        """Mark a chain as completed (reset counter)."""
        chain_id = f"{source}:{event_type}"
        with self._lock:
            if chain_id in self._chains:
                self._chains[chain_id].activations.clear()
                self._chains[chain_id].last_reset = time.time()

    def reset_all(self) -> int:
        with self._lock:
            count = len(self._chains)
            self._chains.clear()
            return count
