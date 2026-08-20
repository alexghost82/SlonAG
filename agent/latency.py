"""Low-overhead, payload-free latency marks for interactive turns."""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field


@dataclass
class LatencyTrace:
    """Record named monotonic timestamps without retaining user/tool payloads."""

    started_at: float = field(default_factory=time.monotonic)
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, event: str) -> None:
        self.marks.setdefault(event, time.monotonic())

    def elapsed_ms(self, start: str | None = None, end: str | None = None) -> float | None:
        left = self.started_at if start is None else self.marks.get(start)
        right = time.monotonic() if end is None else self.marks.get(end)
        if left is None or right is None:
            return None
        return max(0.0, (right - left) * 1000.0)

    def breakdown(self) -> dict[str, float]:
        pairs = {
            "provider": ("provider_request_start", "provider_first_response"),
            "tool": ("tool_execution_start", "tool_execution_finish"),
            "audio": ("observation_returned", "first_audio_output"),
            "total": (None, "turn_complete"),
        }
        result: dict[str, float] = {}
        for name, (start, end) in pairs.items():
            value = self.elapsed_ms(start, end)
            if value is not None:
                result[name] = round(value, 1)
        return result


class TurnLatencyTracker:
    """Thread-safe holder that creates an independent trace for every Live turn."""

    def __init__(self, *, history_limit: int = 100) -> None:
        self._lock = threading.Lock()
        self._current: LatencyTrace | None = None
        self._history_limit = max(1, history_limit)
        self._history: list[dict[str, float]] = []

    @property
    def active(self) -> bool:
        with self._lock:
            return self._current is not None

    def start_turn(self) -> None:
        with self._lock:
            self._current = LatencyTrace()

    def ensure_turn(self) -> None:
        with self._lock:
            if self._current is None:
                self._current = LatencyTrace()

    def mark(self, event: str) -> None:
        with self._lock:
            if self._current is None:
                self._current = LatencyTrace()
            self._current.mark(event)

    def finish_turn(self) -> dict[str, float]:
        with self._lock:
            if self._current is None:
                return {}
            self._current.mark("turn_complete")
            result = self._current.breakdown()
            self._history.append(result)
            del self._history[:-self._history_limit]
            self._current = None
            return dict(result)

    def breakdown(self) -> dict[str, float]:
        with self._lock:
            return self._current.breakdown() if self._current is not None else {}

    def history(self) -> tuple[dict[str, float], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._history)


__all__ = ["LatencyTrace", "TurnLatencyTracker"]
