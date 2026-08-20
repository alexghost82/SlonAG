"""Payload-free realtime events shared by runtime and UI adapters."""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class RuntimeEventKind(StrEnum):
    LISTENING = "listening"
    THINKING = "thinking"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_FINISHED = "tool_finished"
    SPEAKING = "speaking"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RuntimeEvent:
    kind: RuntimeEventKind
    sequence: int
    monotonic_at: float
    turn_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    progress: float | None = None
    code: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("event progress must be between zero and one")


EventSink = Callable[[RuntimeEvent], object]


class RuntimeEventBus:
    """Thread-safe, non-owning fan-out with isolated subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = itertools.count(1)
        self._sinks: list[EventSink] = []

    def subscribe(self, sink: EventSink) -> Callable[[], None]:
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

        def unsubscribe() -> None:
            with self._lock:
                self._sinks = [item for item in self._sinks if item is not sink]

        return unsubscribe

    def emit(self, kind: RuntimeEventKind, **metadata: object) -> RuntimeEvent:
        event = RuntimeEvent(
            kind=kind,
            sequence=next(self._sequence),
            monotonic_at=time.monotonic(),
            **metadata,
        )
        with self._lock:
            sinks = tuple(self._sinks)
        for sink in sinks:
            try:
                sink(event)
            except Exception:
                continue
        return event


class UIRuntimeEventSink:
    """Compatibility adapter from canonical events to the existing UI API."""

    _STATES = {
        RuntimeEventKind.LISTENING: "LISTENING",
        RuntimeEventKind.THINKING: "THINKING",
        RuntimeEventKind.TOOL_STARTED: "THINKING",
        RuntimeEventKind.SPEAKING: "SPEAKING",
    }

    def __init__(self, ui: object) -> None:
        self._ui = ui

    def __call__(self, event: RuntimeEvent) -> None:
        state = self._STATES.get(event.kind)
        if state is not None:
            self._ui.set_state(state)
        control_plane = getattr(self._ui, "control_plane", None)
        if control_plane is not None:
            control_plane.publish(
                "runtime_event",
                {
                    "kind": event.kind.value,
                    "sequence": event.sequence,
                    "monotonic_at": event.monotonic_at,
                    "turn_id": event.turn_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "progress": event.progress,
                    "code": event.code,
                },
            )


__all__ = ["RuntimeEvent", "RuntimeEventBus", "RuntimeEventKind", "UIRuntimeEventSink"]
