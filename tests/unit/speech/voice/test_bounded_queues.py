"""Tests for bounded audio/text queues with stale-discard (VoiceRuntime)."""

from __future__ import annotations

import asyncio
import threading

import pytest

from runtime.canonical_voice import (
    FreshAudioQueue,
    FreshTextQueue,
    PlaybackGeneration,
)


class TestFreshAudioQueue:
    """Bounded queue that drops oldest when full."""

    @pytest.mark.asyncio
    async def test_put_and_get_single(self) -> None:
        q = FreshAudioQueue(maxsize=2)
        await q.put(b"chunk1")
        item = await q.get()
        assert item == b"chunk1"

    @pytest.mark.asyncio
    async def test_drop_oldest_when_full(self) -> None:
        q = FreshAudioQueue(maxsize=2)
        await q.put(b"chunk1")
        await q.put(b"chunk2")
        q.put_nowait(b"chunk3")
        assert q.dropped_chunks == 1
        assert await q.get() == b"chunk2"
        assert await q.get() == b"chunk3"

    @pytest.mark.asyncio
    async def test_multiple_drops(self) -> None:
        q = FreshAudioQueue(maxsize=1)
        q.put_nowait(b"a")
        q.put_nowait(b"b")
        q.put_nowait(b"c")
        assert q.dropped_chunks == 2
        assert await q.get() == b"c"

    @pytest.mark.asyncio
    async def test_full_returns_false_for_regular_put(self) -> None:
        """put_nowait on full queue drops oldest — no exception."""
        q = FreshAudioQueue(maxsize=1)
        await q.put(b"x")
        assert q.full()
        q.put_nowait(b"y")  # drops x, no exception
        assert q.dropped_chunks == 1
        assert await q.get() == b"y"

    @pytest.mark.asyncio
    async def test_empty_queue_raises(self) -> None:
        q = FreshAudioQueue(maxsize=1)
        with pytest.raises(asyncio.QueueEmpty):
            q.get_nowait()


class TestFreshTextQueue:
    """Bounded text queue with stale-discard."""

    @pytest.mark.asyncio
    async def test_put_and_get_single(self) -> None:
        q = FreshTextQueue(maxsize=2)
        await q.put("hello")
        item = await q.get()
        assert item == "hello"

    @pytest.mark.asyncio
    async def test_drop_oldest_when_full(self) -> None:
        q = FreshTextQueue(maxsize=2)
        await q.put("first")
        await q.put("second")
        q.put_nowait("third")
        assert q.dropped_chunks == 1
        assert await q.get() == "second"
        assert await q.get() == "third"

    @pytest.mark.asyncio
    async def test_stale_text_rejected_via_put_nowait(self) -> None:
        """Queue should only deliver the newest chunk (put_nowait path)."""
        q = FreshTextQueue(maxsize=1)
        q.put_nowait("old")
        assert q.dropped_chunks == 0
        q.put_nowait("new")  # drops "old"
        assert q.dropped_chunks == 1
        result = await q.get()
        assert result == "new"


class TestPlaybackGeneration:
    """Monotonically increasing generation for stale audio rejection."""

    def test_initial_value(self) -> None:
        gen = PlaybackGeneration()
        assert gen.value == 0

    def test_bump_increments(self) -> None:
        gen = PlaybackGeneration()
        first = gen.bump()
        second = gen.bump()
        assert first == 1
        assert second == 2

    def test_bump_is_thread_safe(self) -> None:
        gen = PlaybackGeneration()
        values: list[int] = []
        lock = threading.Lock()

        def bump_many() -> None:
            for _ in range(50):
                val = gen.bump()
                with lock:
                    values.append(val)

        threads = [threading.Thread(target=bump_many) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(values) == 200
        assert len(set(values)) == 200

    def test_stale_generation_check(self) -> None:
        gen = PlaybackGeneration()
        gen.bump()
        gen.bump()
        old_val = 1
        assert old_val < gen.value
