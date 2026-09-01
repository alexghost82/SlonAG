"""Bounded, replayable duplex runtime used by the TLS WebSocket adapter."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from gateway.contracts import GatewayEnvelope, GatewayProtocolError
from gateway.router import GatewayContext, GatewayRouter, response_envelope
from gateway.store import GatewayStore, GatewayStoreError


class GatewayBackpressureError(RuntimeError):
    pass


@dataclass(frozen=True)
class SequencedEnvelope:
    sequence: int
    envelope: GatewayEnvelope


class GatewayConnection:
    def __init__(
        self, *, context: GatewayContext, store: GatewayStore,
        router: GatewayRouter, is_active: Callable[[str], bool],
        on_close: Callable[[str], None] | None = None,
        validate_auth: Callable[[], object] | None = None,
        max_pending: int = 128,
    ) -> None:
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self.context = context
        self.store = store
        self.router = router
        self.is_active = is_active
        self.max_pending = max_pending
        self._on_close = on_close
        self._validate_auth = validate_auth
        self._pending: deque[SequencedEnvelope] = deque()
        self.closed = False
        self.last_pong_at = time.monotonic()
        self.last_ping_at = self.last_pong_at
        self.highest_delivered = 0

    def enqueue(self, item: SequencedEnvelope) -> None:
        if self.closed:
            return
        if len(self._pending) >= self.max_pending:
            self.close()
            raise GatewayBackpressureError("slow Gateway consumer disconnected")
        self._pending.append(item)

    def drain(self, limit: int = 128) -> list[SequencedEnvelope]:
        self._assert_active()
        values: list[SequencedEnvelope] = []
        while self._pending and len(values) < limit:
            item = self._pending.popleft()
            self.highest_delivered = max(self.highest_delivered, item.sequence)
            values.append(item)
        return values

    async def receive(self, raw: bytes | str) -> GatewayEnvelope:
        self._assert_active()
        request = GatewayEnvelope.from_json(raw)
        if request.type == "system.ping":
            self.last_pong_at = time.monotonic()
            return response_envelope(request, "system.pong", {})
        if request.type == "system.ack":
            sequence = request.payload.get("sequence")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
                raise GatewayProtocolError("invalid_cursor", "Replay cursor is invalid.")
            if sequence > self.highest_delivered:
                raise GatewayProtocolError(
                    "invalid_cursor", "Replay cursor was not delivered on this connection."
                )
            self.store.set_cursor(
                self.context.device_id, "events", sequence, time.time()
            )
            return response_envelope(request, "system.acknowledged", {"sequence": sequence})
        return await self.router.dispatch(self.context, request)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._pending.clear()
        self.store.close_connection(self.context.connection_id, time.time())
        if self._on_close is not None:
            self._on_close(self.context.connection_id)

    def heartbeat(
        self, *, now: float | None = None, ping_interval: float = 20.0,
        timeout: float = 60.0,
    ) -> bool:
        """Return True when transport should send a ping; close stale peers."""
        current = time.monotonic() if now is None else now
        if current - self.last_pong_at > timeout:
            self.close()
            raise GatewayProtocolError("ping_timeout", "Gateway peer timed out.")
        if current - self.last_ping_at >= ping_interval:
            self.last_ping_at = current
            return True
        return False

    def _assert_active(self) -> None:
        if self.closed:
            raise GatewayProtocolError("connection_closed", "Gateway connection is closed.")
        if not self.is_active(self.context.device_id):
            self.close()
            raise GatewayProtocolError("revoked", "Device is no longer trusted.")
        if self._validate_auth is not None:
            try:
                self._validate_auth()
            except Exception as exc:
                self.close()
                raise GatewayProtocolError(
                    "unauthorized", "Gateway connection authorization expired."
                ) from exc


class GatewayWebSocketRuntime:
    def __init__(
        self, *, store: GatewayStore, router: GatewayRouter,
        is_active: Callable[[str], bool], workspace_for: Callable[[str], str],
        max_pending: int = 128,
        replay_limit: int = 1000,
    ) -> None:
        self.store = store
        self.router = router
        self.is_active = is_active
        self.workspace_for = workspace_for
        self.max_pending = max_pending
        self.replay_limit = replay_limit
        self._connections: dict[str, GatewayConnection] = {}
        self._lock = threading.RLock()

    async def connect(
        self, *, device_id: str, after_sequence: int | None = None,
        validate_auth: Callable[[], object] | None = None,
    ) -> GatewayConnection:
        if not self.is_active(device_id):
            raise GatewayProtocolError("unauthorized", "Device is not trusted.")
        workspace_id = self.workspace_for(device_id)
        connection_id = str(uuid4())
        self.store.open_connection(connection_id, device_id, time.time())
        connection = GatewayConnection(
            context=GatewayContext(device_id, workspace_id, connection_id),
            store=self.store, router=self.router, is_active=self.is_active,
            on_close=self._remove_connection,
            validate_auth=validate_auth,
            max_pending=self.max_pending,
        )
        cursor = (
            self.store.cursor(device_id, "events")
            if after_sequence is None else after_sequence
        )
        try:
            replay = self.store.events_after(
                workspace_id=workspace_id, sequence=cursor,
                limit=min(self.replay_limit, self.max_pending),
            )
        except GatewayStoreError as exc:
            connection.close()
            raise GatewayProtocolError("replay_gap", "Replay cursor expired.") from exc
        for sequence, raw in replay:
            connection.enqueue(SequencedEnvelope(sequence, GatewayEnvelope.from_json(raw)))
        with self._lock:
            self._connections[connection_id] = connection
        return connection

    def _remove_connection(self, connection_id: str) -> None:
        with self._lock:
            self._connections.pop(connection_id, None)

    def close(self) -> None:
        with self._lock:
            connections = tuple(self._connections.values())
        for connection in connections:
            connection.close()

    async def publish(self, workspace_id: str, envelope: GatewayEnvelope) -> int:
        return self.publish_now(workspace_id, envelope)

    def publish_now(self, workspace_id: str, envelope: GatewayEnvelope) -> int:
        sequence = self.store.append_event(
            workspace_id=workspace_id, session_id=envelope.session_id,
            envelope_json=envelope.to_json().decode("utf-8"), created_at=time.time(),
        )
        item = SequencedEnvelope(sequence, envelope)
        with self._lock:
            targets = list(self._connections.items())
        stale: list[str] = []
        for connection_id, connection in targets:
            if connection.context.workspace_id != workspace_id:
                continue
            try:
                connection.enqueue(item)
            except GatewayBackpressureError:
                stale.append(connection_id)
        if stale:
            with self._lock:
                for connection_id in stale:
                    self._connections.pop(connection_id, None)
        return sequence


__all__ = [
    "GatewayBackpressureError", "GatewayConnection", "GatewayWebSocketRuntime",
    "SequencedEnvelope",
]
