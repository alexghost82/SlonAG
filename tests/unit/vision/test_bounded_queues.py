"""Tests for bounded queues in Vision Runtime.

Covers:
- BoundedFrameQueue: capacity enforcement, stale dropping
- BoundedDetectionQueue: capacity enforcement
- BoundedEventQueue: capacity enforcement
- BoundedTrajectoryStore: per-track bounded history
"""

import asyncio
import time

import pytest

from acta.vision.queues import (
    BoundedDetectionQueue,
    BoundedEventQueue,
    BoundedFrameQueue,
    BoundedTrajectoryStore,
)
from acta.vision.types import Frame, DetectionResult, FrameEvent, FrameSource, Bbox


@pytest.fixture
def loop():
    return asyncio.new_event_loop()


# ── BoundedFrameQueue ──────────────────────────────────────────────

class TestBoundedFrameQueue:
    """Tests for BoundedFrameQueue."""

    @pytest.mark.asyncio
    async def test_put_and_get(self, loop):
        q = BoundedFrameQueue(maxlen=5)
        frame = Frame(index=0, source=FrameSource.IMAGE_FILE, raw=b"\x00")
        await q.put(frame)
        result = await q.get()
        assert result is frame
        assert q.is_empty

    @pytest.mark.asyncio
    async def test_bounded_capacity(self, loop):
        q = BoundedFrameQueue(maxlen=3)
        for i in range(10):
            await q.put(Frame(index=i, source=FrameSource.IMAGE_FILE, raw=b"\x00"))
        assert q.count == 3  # should be capped

    @pytest.mark.asyncio
    async def test_drain(self, loop):
        q = BoundedFrameQueue(maxlen=5)
        for i in range(5):
            await q.put(Frame(index=i, source=FrameSource.IMAGE_FILE, raw=b"\x00"))
        items = await q.drain()
        assert len(items) == 5
        assert q.is_empty

    @pytest.mark.asyncio
    async def test_stale_dropping(self, loop):
        q = BoundedFrameQueue(maxlen=5, max_age_seconds=0.1)
        old_frame = Frame(index=0, source=FrameSource.IMAGE_FILE, raw=b"\x00", timestamp=time.time() - 5.0)
        result = await q.put(old_frame)
        assert result is False  # stale frame rejected

    @pytest.mark.asyncio
    async def test_is_full(self, loop):
        q = BoundedFrameQueue(maxlen=2)
        assert q.is_full is False
        await q.put(Frame(index=0, source=FrameSource.IMAGE_FILE, raw=b"\x00"))
        await q.put(Frame(index=1, source=FrameSource.IMAGE_FILE, raw=b"\x00"))
        assert q.is_full is True


# ── BoundedDetectionQueue ─────────────────────────────────────────

class TestBoundedDetectionQueue:
    """Tests for BoundedDetectionQueue."""

    @pytest.mark.asyncio
    async def test_put_and_get(self, loop):
        q = BoundedDetectionQueue(maxlen=5)
        det = DetectionResult(kind="object", label="box", confidence=0.9, bbox=Bbox(0, 0, 1, 1))
        await q.put(det)
        result = await q.get()
        assert result is det

    @pytest.mark.asyncio
    async def test_bounded_capacity(self, loop):
        q = BoundedDetectionQueue(maxlen=3)
        for i in range(10):
            det = DetectionResult(kind="object", label="box", confidence=0.9, bbox=Bbox(0, 0, 1, 1))
            await q.put(det)
        assert q.count == 3


# ── BoundedEventQueue ──────────────────────────────────────────────

class TestBoundedEventQueue:
    """Tests for BoundedEventQueue."""

    @pytest.mark.asyncio
    async def test_put_and_drain(self, loop):
        q = BoundedEventQueue(maxlen=10)
        for i in range(10):
            await q.put(FrameEvent(
                event_type="appearance", track_id=f"t{i}",
                timestamp=time.time(), description=f"event {i}",
            ))
        items = await q.drain()
        assert len(items) == 10

    @pytest.mark.asyncio
    async def test_bounded_capacity(self, loop):
        q = BoundedEventQueue(maxlen=5)
        for i in range(20):
            await q.put(FrameEvent(
                event_type="appearance", track_id=f"t{i}",
                timestamp=time.time(), description=f"event {i}",
            ))
        assert q.count == 5


# ── BoundedTrajectoryStore ─────────────────────────────────────────

class TestBoundedTrajectoryStore:
    """Tests for BoundedTrajectoryStore."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, loop):
        store = BoundedTrajectoryStore(default_maxlen=5)
        await store.add("track1", {"cx": 0.5, "cy": 0.5})
        pts = await store.get("track1")
        assert len(pts) == 1
        assert pts[0]["cx"] == 0.5

    @pytest.mark.asyncio
    async def test_bounded_per_track(self, loop):
        store = BoundedTrajectoryStore(default_maxlen=3)
        for i in range(10):
            await store.add("track1", {"cx": i * 0.1, "cy": 0.5})
        pts = await store.get("track1")
        assert len(pts) == 3  # bounded

    @pytest.mark.asyncio
    async def test_independent_tracks(self, loop):
        store = BoundedTrajectoryStore(default_maxlen=5)
        for i in range(3):
            await store.add("t1", {"cx": i})
            await store.add("t2", {"cy": i})
        assert len(await store.get("t1")) == 3
        assert len(await store.get("t2")) == 3
        assert "t1" in store.track_ids
        assert "t2" in store.track_ids

    @pytest.mark.asyncio
    async def test_remove(self, loop):
        store = BoundedTrajectoryStore()
        await store.add("t1", {"cx": 0})
        await store.remove("t1")
        assert len(await store.get("t1")) == 0
