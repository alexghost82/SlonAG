"""Unit tests for agent/steering.py."""

import asyncio
import threading
import time
import pytest
from agent.steering import SteeringKind, SteeringSignal, SteeringQueue


def test_steering_kind_enum_members():
    """Verify SteeringKind enum members exist and match expected string values."""
    assert SteeringKind.USER_INTERRUPT.value == "USER_INTERRUPT"
    assert SteeringKind.USER_GUIDANCE.value == "USER_GUIDANCE"
    assert SteeringKind.VOICE_INTERRUPTION.value == "VOICE_INTERRUPTION"
    assert SteeringKind.SYSTEM_CANCEL.value == "SYSTEM_CANCEL"

    assert len(SteeringKind) == 4


def test_steering_signal_dataclass_defaults():
    """Verify SteeringSignal defaults and custom attributes."""
    before = time.time()
    signal = SteeringSignal(kind=SteeringKind.USER_INTERRUPT)
    after = time.time()

    assert signal.kind == SteeringKind.USER_INTERRUPT
    assert signal.text is None
    assert signal.priority == 0
    assert before <= signal.timestamp <= after


def test_steering_signal_dataclass_custom_values():
    """Verify SteeringSignal with explicit values."""
    signal = SteeringSignal(
        kind=SteeringKind.USER_GUIDANCE,
        text="Please stop writing files",
        priority=10,
        timestamp=123456789.0,
    )

    assert signal.kind == SteeringKind.USER_GUIDANCE
    assert signal.text == "Please stop writing files"
    assert signal.priority == 10
    assert signal.timestamp == 123456789.0


def test_steering_queue_basic_push_and_pop():
    """Verify basic push, is_empty, len, and pop operations."""
    queue = SteeringQueue()

    assert queue.is_empty() is True
    assert len(queue) == 0
    assert queue.pop_highest_priority() is None

    s1 = SteeringSignal(kind=SteeringKind.USER_GUIDANCE, text="guidance 1")
    queue.push(s1)

    assert queue.is_empty() is False
    assert len(queue) == 1

    popped = queue.pop_highest_priority()
    assert popped is s1
    assert queue.is_empty() is True
    assert len(queue) == 0
    assert queue.pop_highest_priority() is None


def test_steering_queue_priority_ordering():
    """Verify queue pops signals in descending order of priority."""
    queue = SteeringQueue()

    low_prio = SteeringSignal(kind=SteeringKind.USER_GUIDANCE, text="low", priority=0)
    mid_prio = SteeringSignal(kind=SteeringKind.VOICE_INTERRUPTION, text="mid", priority=5)
    high_prio = SteeringSignal(kind=SteeringKind.USER_INTERRUPT, text="high", priority=10)
    neg_prio = SteeringSignal(kind=SteeringKind.SYSTEM_CANCEL, text="neg", priority=-1)

    # Push out of order
    queue.push(mid_prio)
    queue.push(neg_prio)
    queue.push(high_prio)
    queue.push(low_prio)

    assert queue.pop_highest_priority() is high_prio
    assert queue.pop_highest_priority() is mid_prio
    assert queue.pop_highest_priority() is low_prio
    assert queue.pop_highest_priority() is neg_prio
    assert queue.pop_highest_priority() is None


def test_steering_queue_fifo_for_equal_priority():
    """Verify signals with equal priority are popped in FIFO order."""
    queue = SteeringQueue()

    s1 = SteeringSignal(kind=SteeringKind.USER_GUIDANCE, text="first", priority=5)
    s2 = SteeringSignal(kind=SteeringKind.VOICE_INTERRUPTION, text="second", priority=5)
    s3 = SteeringSignal(kind=SteeringKind.USER_GUIDANCE, text="third", priority=5)

    queue.push(s1)
    queue.push(s2)
    queue.push(s3)

    assert queue.pop_highest_priority() is s1
    assert queue.pop_highest_priority() is s2
    assert queue.pop_highest_priority() is s3


def test_steering_queue_has_cancellation():
    """Verify has_cancellation returns True only if SYSTEM_CANCEL or USER_INTERRUPT is queued."""
    queue = SteeringQueue()

    assert queue.has_cancellation() is False

    g1 = SteeringSignal(kind=SteeringKind.USER_GUIDANCE, text="guidance")
    v1 = SteeringSignal(kind=SteeringKind.VOICE_INTERRUPTION, text="voice")
    queue.push(g1)
    queue.push(v1)
    assert queue.has_cancellation() is False

    # Push system cancel
    c1 = SteeringSignal(kind=SteeringKind.SYSTEM_CANCEL)
    queue.push(c1)
    assert queue.has_cancellation() is True

    # Pop cancel signal
    queue.pop_highest_priority()  # Could be c1 or highest priority
    queue.clear()
    assert queue.has_cancellation() is False

    # Push user interrupt
    u1 = SteeringSignal(kind=SteeringKind.USER_INTERRUPT)
    queue.push(u1)
    assert queue.has_cancellation() is True


def test_steering_queue_clear():
    """Verify clear removes all elements from the queue."""
    queue = SteeringQueue()

    queue.push(SteeringSignal(kind=SteeringKind.USER_GUIDANCE, priority=1))
    queue.push(SteeringSignal(kind=SteeringKind.SYSTEM_CANCEL, priority=10))

    assert len(queue) == 2
    assert queue.is_empty() is False

    queue.clear()

    assert len(queue) == 0
    assert queue.is_empty() is True
    assert queue.has_cancellation() is False
    assert queue.pop_highest_priority() is None


def test_steering_queue_thread_safety():
    """Verify concurrent push and pop across multiple threads."""
    queue = SteeringQueue()
    num_threads = 10
    pushes_per_thread = 100
    popped_items: list[SteeringSignal] = []
    lock = threading.Lock()

    def pusher(thread_id: int):
        for i in range(pushes_per_thread):
            signal = SteeringSignal(
                kind=SteeringKind.USER_GUIDANCE,
                text=f"t{thread_id}-i{i}",
                priority=thread_id,
            )
            queue.push(signal)

    def popper():
        for _ in range(pushes_per_thread * num_threads // 2):
            item = queue.pop_highest_priority()
            if item is not None:
                with lock:
                    popped_items.append(item)

    threads = []
    for t_id in range(num_threads):
        t = threading.Thread(target=pusher, args=(t_id,))
        threads.append(t)
        t.start()

    popper_threads = []
    for _ in range(2):
        t = threading.Thread(target=popper)
        popper_threads.append(t)
        t.start()

    for t in threads:
        t.join()
    for t in popper_threads:
        t.join()

    # Empty remaining
    while not queue.is_empty():
        item = queue.pop_highest_priority()
        if item is not None:
            popped_items.append(item)

    assert len(popped_items) == num_threads * pushes_per_thread


@pytest.mark.asyncio
async def test_steering_queue_asyncio_safety():
    """Verify concurrent operations across asyncio tasks."""
    queue = SteeringQueue()

    async def async_producer(task_id: int):
        for i in range(50):
            queue.push(
                SteeringSignal(
                    kind=SteeringKind.USER_GUIDANCE,
                    text=f"task{task_id}-{i}",
                    priority=i,
                )
            )
            await asyncio.sleep(0.0001)

    async def async_consumer():
        received = 0
        for _ in range(100):
            if queue.pop_highest_priority() is not None:
                received += 1
            await asyncio.sleep(0.0001)
        return received

    producers = [asyncio.create_task(async_producer(i)) for i in range(4)]
    consumer = asyncio.create_task(async_consumer())

    await asyncio.gather(*producers, consumer)

    # Pop rest
    remaining = 0
    while queue.pop_highest_priority() is not None:
        remaining += 1

    total_processed = consumer.result() + remaining
    assert total_processed == 200
