"""Infinite click-loop detector for the vision-computer closed loop.

Tracks a sliding window of recent clicks (target + fingerprint pair).
When the same target is clicked too many times without a
meaningful screen-change, the detector flags a ``LoopBreakError``.

This prevents the agent from endlessly clicking a non-responsive
button or fighting an element that keeps reverting to the same state.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


class LoopBreakError(Exception):
    """Detected that the agent is stuck in a click loop."""

    def __init__(
        self,
        target: str,
        repeat_count: int,
        window_size: int,
        last_fingerprints: list[str],
    ) -> None:
        self.target = target
        self.repeat_count = repeat_count
        self.window_size = window_size
        self.last_fingerprints = list(last_fingerprints)
        super().__init__(
            f"Обнаружена петля кликов: кнопка '{target}' нажата "
            f"{repeat_count} раз(а) подряд в окне из {window_size} "
            f"последних действий без значимого изменения экрана. "
            f"Последние отпечатки: {last_fingerprints[:3]}"
        )


@dataclass
class ClickRecord:
    """A single click event recorded for loop detection."""

    target: str
    pre_fingerprint: str
    post_fingerprint: str
    timestamp: float = field(default_factory=time.monotonic)
    changed: bool = False


class ClickLoopDetector:
    """Sliding-window click-loop detector.

    Parameters
    ----------
    window_size :
        Number of recent click records to examine (default 10).
    max_repeats :
        Maximum consecutive identical-target clicks before raising
        ``LoopBreakError`` (default 3).
    """

    def __init__(
        self,
        window_size: int = 10,
        max_repeats: int = 3,
    ) -> None:
        self._window_size = window_size
        self._max_repeats = max_repeats
        self._records: deque[ClickRecord] = deque(maxlen=window_size)
        self._active: bool = True  # can be toggled off

    # -- public API ------------------------------------------------

    def record(self, record: ClickRecord) -> None:
        """Register a click event.

        After insertion checks for loops and raises
        ``LoopBreakError`` if the limit is exceeded.
        """
        if not self._active:
            return
        self._records.append(record)
        self._check_loop()

    def record_from(
        self,
        target: str,
        pre_fp: str,
        post_fp: str,
        changed: bool,
    ) -> None:
        """Convenience wrapper around :meth:`record`."""
        self.record(ClickRecord(target, pre_fp, post_fp, changed=changed))

    def reset(self) -> None:
        """Clear the sliding window (e.g. after a successful action)."""
        self._records.clear()

    def disable(self) -> None:
        """Temporarily disable detection."""
        self._active = False

    def enable(self) -> None:
        """Re-enable detection after it was disabled."""
        self._active = True

    @property
    def window(self) -> list[ClickRecord]:
        """Snapshot of the current sliding window."""
        return list(self._records)

    @property
    def window_size(self) -> int:
        return self._window_size

    # -- internal --------------------------------------------------

    def _check_loop(self) -> None:
        """Scan the window for a repeating target with no screen change."""
        if len(self._records) < 2:
            return

        # Look for the longest suffix of records targeting the same element
        # where none of them produced a meaningful screen change.
        last = self._records[-1]
        consecutive_same_target = 1
        consecutive_no_change = 0

        for rec in reversed(self._records[:-1]):
            if rec.target != last.target:
                break
            consecutive_same_target += 1
            if rec.changed:
                consecutive_no_change = 0  # reset counter on any change
            else:
                consecutive_no_change += 1

        if (
            consecutive_same_target >= self._max_repeats
            and consecutive_no_change >= self._max_repeats - 1
        ):
            fps = [r.post_fingerprint for r in self._records]
            raise LoopBreakError(
                target=last.target,
                repeat_count=consecutive_same_target,
                window_size=self._window_size,
                last_fingerprints=fps,
            )


# Module-level singleton for convenience (used by closed_loop.py)
_default_detector: ClickLoopDetector | None = None


def get_detector() -> ClickLoopDetector:
    """Return the module-level singleton detector."""
    global _default_detector
    if _default_detector is None:
        _default_detector = ClickLoopDetector()
    return _default_detector


def reset_detector() -> None:
    """Reset the singleton detector."""
    global _default_detector
    _default_detector = ClickLoopDetector()
