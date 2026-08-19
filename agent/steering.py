"""Steering signals and queue management for Slon agent loop."""

import heapq
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SteeringKind(Enum):
    """Types of steering signals that can be sent to the agent loop."""
    USER_INTERRUPT = "USER_INTERRUPT"
    USER_GUIDANCE = "USER_GUIDANCE"
    VOICE_INTERRUPTION = "VOICE_INTERRUPTION"
    SYSTEM_CANCEL = "SYSTEM_CANCEL"


@dataclass
class SteeringSignal:
    """Represents a steering signal injected into the agent loop."""
    kind: SteeringKind
    text: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    priority: int = 0


class SteeringQueue:
    """Thread-safe & asyncio-safe queue for prioritizing and retrieving steering signals."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter: int = 0
        # Tuple format: (-priority, sequence_number, signal)
        self._heap: list[tuple[int, int, SteeringSignal]] = []

    def push(self, signal: SteeringSignal) -> None:
        """Push a steering signal into the queue."""
        with self._lock:
            self._counter += 1
            entry = (-signal.priority, self._counter, signal)
            heapq.heappush(self._heap, entry)

    def pop_highest_priority(self) -> Optional[SteeringSignal]:
        """Pop and return the signal with highest priority, or None if empty."""
        with self._lock:
            if not self._heap:
                return None
            _, _, signal = heapq.heappop(self._heap)
            return signal

    def has_cancellation(self) -> bool:
        """Return True if any cancellation or interrupt signal is present in the queue."""
        with self._lock:
            cancellation_kinds = {SteeringKind.SYSTEM_CANCEL, SteeringKind.USER_INTERRUPT}
            return any(entry[2].kind in cancellation_kinds for entry in self._heap)

    def clear(self) -> None:
        """Remove all signals from the queue."""
        with self._lock:
            self._heap.clear()

    def is_empty(self) -> bool:
        """Return True if the queue contains no signals."""
        with self._lock:
            return len(self._heap) == 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._heap)
