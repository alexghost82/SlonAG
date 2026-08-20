"""Low-overhead, payload-free latency marks for interactive turns."""

from __future__ import annotations

import time
import threading
import math
import statistics
from dataclasses import dataclass, field
from enum import StrEnum


class LatencyEvent(StrEnum):
    INPUT_ACTIVITY_START = "user_input_activity_start"
    INPUT_ACTIVITY_END = "user_input_activity_end"
    PROVIDER_DISPATCH = "provider_request_start"
    PROVIDER_FIRST_EVENT = "provider_first_response"
    TOOL_CALL_RECEIVED = "tool_call_received"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_FINISH = "tool_execution_finish"
    OBSERVATION_RETURNED = "observation_returned"
    POST_TOOL_PROVIDER_FIRST_EVENT = "provider_after_tool_first_response"
    FIRST_AUDIO_FRAME = "first_audio_output"
    TURN_COMPLETE = "turn_complete"


@dataclass
class LatencyTrace:
    """Record named monotonic timestamps without retaining user/tool payloads."""

    started_at: float = field(default_factory=time.monotonic)
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, event: str | LatencyEvent) -> None:
        self.marks.setdefault(str(event), time.monotonic())

    def mark_at(self, event: str | LatencyEvent, monotonic_at: float | None) -> None:
        if monotonic_at is not None:
            self.marks.setdefault(str(event), monotonic_at)

    def elapsed_ms(self, start: str | None = None, end: str | None = None) -> float | None:
        left = self.started_at if start is None else self.marks.get(start)
        right = time.monotonic() if end is None else self.marks.get(end)
        if left is None or right is None:
            return None
        return max(0.0, (right - left) * 1000.0)

    def breakdown(self) -> dict[str, float]:
        pairs = {
            "input_first_chunk_to_response": (
                "user_input_activity_start",
                "provider_first_response",
            ),
            "provider": ("provider_request_start", "provider_first_response"),
            "input_activity": ("user_input_activity_start", "user_input_activity_end"),
            "tool": ("tool_execution_start", "tool_execution_finish"),
            "approval": ("approval_start", "approval_finish"),
            "tool_handler": ("tool_handler_start", "tool_execution_finish"),
            "post_tool_provider": (
                "observation_returned",
                "provider_after_tool_first_response",
            ),
            "audio_first": ("provider_first_response", "first_audio_output"),
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

    def mark_at(self, event: str | LatencyEvent, monotonic_at: float | None) -> None:
        with self._lock:
            if self._current is None:
                self._current = LatencyTrace()
            self._current.mark_at(event, monotonic_at)

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

    def cancel_turn(self) -> None:
        """Discard an interrupted turn without recording it as completed."""
        with self._lock:
            self._current = None

    def breakdown(self) -> dict[str, float]:
        with self._lock:
            return self._current.breakdown() if self._current is not None else {}

    def history(self) -> tuple[dict[str, float], ...]:
        with self._lock:
            return tuple(dict(item) for item in self._history)

    def statistics(self) -> dict[str, dict[str, float | int]]:
        """Return payload-free per-metric min/median/p90/p95/max aggregates."""
        with self._lock:
            history = tuple(dict(item) for item in self._history)
        metrics = sorted({name for turn in history for name in turn})
        result: dict[str, dict[str, float | int]] = {}
        for metric in metrics:
            values = sorted(turn[metric] for turn in history if metric in turn)
            if not values:
                continue
            p95_index = max(0, math.ceil(0.95 * len(values)) - 1)
            p90_index = max(0, math.ceil(0.90 * len(values)) - 1)
            result[metric] = {
                "count": len(values),
                "min": round(values[0], 1),
                "median": round(statistics.median(values), 1),
                "p90": round(values[p90_index], 1),
                "p95": round(values[p95_index], 1),
                "max": round(values[-1], 1),
            }
        return result


__all__ = ["LatencyEvent", "LatencyTrace", "TurnLatencyTracker"]
