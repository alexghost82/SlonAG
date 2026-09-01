"""In-process event hub mock for ``/v1/events``.

No real WebSocket server, no ``0.0.0.0`` listen, no sockets.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock

from server.routes._common import DevicePrincipal
from server.schemas import CODE_UNAUTHORIZED, ApiError


class EventsUnauthorizedError(Exception):
    """Raised when subscribe is attempted without an active principal."""

    def __init__(self, message: str | None = None) -> None:
        self.code = CODE_UNAUTHORIZED
        self.error = ApiError.of(CODE_UNAUTHORIZED, message)
        super().__init__(self.error.message)


@dataclass
class EventSubscription:
    """Buffered in-process subscription. ``poll`` drains queued events."""

    device_id: str
    _queue: list[dict[str, object]] = field(default_factory=list)
    closed: bool = False
    _lock: Lock = field(default_factory=Lock, repr=False)

    def push(self, event: Mapping[str, object]) -> None:
        with self._lock:
            if self.closed:
                return
            self._queue.append(deepcopy(dict(event)))

    def poll(self) -> list[dict[str, object]]:
        with self._lock:
            if self.closed:
                return []
            drained = list(self._queue)
            self._queue.clear()
            return drained

    def close(self) -> None:
        with self._lock:
            self.closed = True
            self._queue.clear()


class EventsHub:
    """Subscribe / publish hub. Unauthenticated subscribe fails."""

    def __init__(self) -> None:
        self._subs: list[EventSubscription] = []
        self._lock = Lock()

    def subscribe(
        self,
        *,
        principal: DevicePrincipal | None,
    ) -> EventSubscription:
        if principal is None:
            raise EventsUnauthorizedError()
        if principal.revoked:
            raise EventsUnauthorizedError("Device credential has been revoked.")
        sub = EventSubscription(device_id=principal.device_id)
        with self._lock:
            self._subs.append(sub)
        return sub

    def publish(self, event: Mapping[str, object]) -> int:
        """Fan-out to active subscribers. Returns delivery count."""
        payload = dict(event)
        delivered = 0
        alive: list[EventSubscription] = []
        with self._lock:
            for sub in self._subs:
                if sub.closed:
                    continue
                sub.push(payload)
                delivered += 1
                alive.append(sub)
            self._subs = alive
        return delivered

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return sum(1 for sub in self._subs if not sub.closed)


__all__ = [
    "EventSubscription",
    "EventsHub",
    "EventsUnauthorizedError",
]
