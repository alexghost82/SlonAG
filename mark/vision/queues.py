"""Vision Runtime — bounded queues and stale frame dropping.

All queues are bounded (maxlen). Stale frames are dropped automatically.
"""

from __future__ import annotations

import asyncio
import collections
import time
from typing import Any

from mark.vision.types import Frame, DetectionResult, FrameEvent


class BoundedFrameQueue:
    """Async bounded queue for frames with stale frame dropping."""

    def __init__(self, maxlen: int = 30, max_age_seconds: float = 5.0) -> None:
        self._queue: collections.deque[Frame] = collections.deque(maxlen=maxlen)
        self._lock = asyncio.Lock()
        self._maxlen = maxlen
        self._max_age_seconds = max_age_seconds

    async def put(self, frame: Frame) -> bool:
        if frame.age > self._max_age_seconds:
            return False
        async with self._lock:
            self._queue.append(frame)
            return True

    async def get(self) -> Frame | None:
        async with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def drain(self) -> list[Frame]:
        async with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    @property
    def count(self) -> int:
        return len(self._queue)

    @property
    def maxlen(self) -> int:
        return self._maxlen

    @property
    def is_full(self) -> bool:
        return len(self._queue) >= self._maxlen

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0


class BoundedDetectionQueue:
    """Bounded async queue for detection results."""

    def __init__(self, maxlen: int = 60) -> None:
        self._queue: collections.deque[DetectionResult] = collections.deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def put(self, result: DetectionResult) -> bool:
        async with self._lock:
            self._queue.append(result)
            return True

    async def get(self) -> DetectionResult | None:
        async with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    @property
    def count(self) -> int:
        return len(self._queue)


class BoundedEventQueue:
    """Bounded async queue for frame events."""

    def __init__(self, maxlen: int = 200) -> None:
        self._queue: collections.deque[FrameEvent] = collections.deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def put(self, event: FrameEvent) -> bool:
        async with self._lock:
            self._queue.append(event)
            return True

    async def get(self) -> FrameEvent | None:
        async with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    async def drain(self) -> list[FrameEvent]:
        async with self._lock:
            items = list(self._queue)
            self._queue.clear()
            return items

    @property
    def count(self) -> int:
        return len(self._queue)


class BoundedTrajectoryStore:
    """Bounded per-track trajectory history."""

    def __init__(self, default_maxlen: int = 200) -> None:
        self._stores: dict[str, collections.deque] = {}
        self._lock = asyncio.Lock()
        self._default_maxlen = default_maxlen

    async def add(self, track_id: str, point: Any) -> None:
        async with self._lock:
            if track_id not in self._stores:
                self._stores[track_id] = collections.deque(maxlen=self._default_maxlen)
            self._stores[track_id].append(point)

    async def get(self, track_id: str) -> list[Any]:
        async with self._lock:
            store = self._stores.get(track_id)
            return list(store) if store else []

    async def remove(self, track_id: str) -> None:
        async with self._lock:
            self._stores.pop(track_id, None)

    @property
    def track_ids(self) -> list[str]:
        return list(self._stores.keys())
