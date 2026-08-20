"""Low-overhead, payload-free latency marks for interactive turns."""

from __future__ import annotations

import time
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


__all__ = ["LatencyTrace"]
