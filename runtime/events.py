"""Canonical runtime event bus shared by runtime and UI adapters.

Do not create a second bus. Tool argument/result payloads stay off the
legacy UI fields; optional ``payload`` is for typed control-plane data.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


SCHEMA_VERSION = 1
HISTORY_LIMIT = 256


class RuntimeEventKind(StrEnum):
    LISTENING = "listening"
    THINKING = "thinking"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_FINISHED = "tool_finished"
    SPEAKING = "speaking"
    CANCELLED = "cancelled"
    JOB_PROGRESS = "job_progress"
    ERROR = "error"
    SESSION_CHANGED = "session_changed"
    APPROVAL_REQUIRED = "approval_required"
    ASSISTANT_TEXT = "assistant_text"


@dataclass(frozen=True)
class RuntimeEvent:
    kind: RuntimeEventKind
    sequence: int
    monotonic_at: float
    session_id: str | None = None
    connection_generation: int | None = None
    turn_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    progress: float | None = None
    code: str | None = None
    event_id: str = ""
    source: str = "runtime"
    job_id: str | None = None
    correlation_id: str | None = None
    schema_version: int = SCHEMA_VERSION
    timestamp: str = ""
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("event progress must be between zero and one")
        if not self.event_id:
            object.__setattr__(self, "event_id", uuid4().hex)
        if not self.timestamp:
            object.__setattr__(
                self,
                "timestamp",
                datetime.now(UTC).replace(microsecond=0).isoformat(),
            )

    @property
    def event_type(self) -> str:
        return self.kind.value


EventSink = Callable[[RuntimeEvent], object]


class RuntimeEventBus:
    """Thread-safe fan-out: ordered sequence, isolated subscribers, replay.

    Delivery is at-most-once for live sinks. Replay is explicit via
    ``replay(after_sequence=)``. History is a bounded ring (backpressure).
    """

    def __init__(self, *, history_limit: int = HISTORY_LIMIT) -> None:
        self._lock = threading.Lock()
        self._sequence = itertools.count(1)
        self._sinks: list[EventSink] = []
        self._history: list[RuntimeEvent] = []
        self._history_limit = max(1, int(history_limit))

    def subscribe(self, sink: EventSink) -> Callable[[], None]:
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

        def unsubscribe() -> None:
            with self._lock:
                self._sinks = [item for item in self._sinks if item is not sink]

        return unsubscribe

    def emit(self, kind: RuntimeEventKind, **metadata: object) -> RuntimeEvent:
        with self._lock:
            event = RuntimeEvent(
                kind=kind,
                sequence=next(self._sequence),
                monotonic_at=time.monotonic(),
                **metadata,  # type: ignore[arg-type]
            )
            self._history.append(event)
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit :]
            sinks = tuple(self._sinks)
        for sink in sinks:
            try:
                sink(event)
            except Exception:
                continue
        return event

    def replay(self, *, after_sequence: int = 0) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            return tuple(
                event for event in self._history if event.sequence > after_sequence
            )


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
                    "session_id": event.session_id,
                    "connection_generation": event.connection_generation,
                    "turn_id": event.turn_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "progress": event.progress,
                    "code": event.code,
                    "event_id": event.event_id,
                    "source": event.source,
                    "job_id": event.job_id,
                    "correlation_id": event.correlation_id,
                    "schema_version": event.schema_version,
                    "timestamp": event.timestamp,
                },
            )


__all__ = [
    "HISTORY_LIMIT",
    "SCHEMA_VERSION",
    "RuntimeEvent",
    "RuntimeEventBus",
    "RuntimeEventKind",
    "UIRuntimeEventSink",
]
