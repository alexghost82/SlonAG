"""Session state machine for LAN/Remote connectivity.

Manages the connection lifecycle: connecting, connected, migrating, disconnected, error.
Integrates discovery, transport, migration, and monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from mark.connectivity.discovery import LANDevice, LANDeviceScanner
from mark.connectivity.migration import LANRemoteMigration
from mark.connectivity.monitor import ConnectivityMonitor
from mark.connectivity.remote import RemoteAdapter, RemoteAdapterError
from mark.connectivity.transport import LANTransport, LANTransportError, TransportConfig
from mark.connectivity.types import (
    ConnectionConnectionReason,
    ConnectionInfo,
    ConnectionState,
    ConnectionReason,
    ConnectivityMode,
    ConnectivityPolicy,
    MigrationEvent,
    TransportKind,
)

logger = logging.getLogger(__name__)


class ConnectivitySessionError(RuntimeError):
    """Session-level error."""

    def __init__(self, message: str, *, code: str = "session_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ConnectivitySession:
    """Central session object that manages LAN/remote connectivity.

    This is the primary API for application code:
    - Connect to a LAN device (auto-discovered or specified).
    - Monitor connection health and auto-reconnect.
    - Migrate between LAN and remote transports seamlessly.
    - Query the current connection state and info.
    """

    policy: ConnectivityPolicy | None = None
    _device_scanner: LANDeviceScanner | None = None
    _transport: LANTransport | None = None
    _remote_adapter: RemoteAdapter | None = None
    _migration: LANRemoteMigration | None = None
    _monitor: ConnectivityMonitor | None = None
    _connecting: bool = False

    # State
    state: ConnectionState = ConnectionState.DISCONNECTED
    reason: str = ""
    current_device: LANDevice | None = None
    current_transport: TransportKind = TransportKind.LOCAL

    # Callbacks
    _state_handlers: list[Any] = field(default_factory=list)
    _message_handlers: list[callable] = field(default_factory=list)

    # Async primitives
    _lock: asyncio.Lock | None = None
    _stop_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        if self.policy is None:
            from mark.connectivity.types import ConnectivityPolicy
            self.policy = ConnectivityPolicy()

    # -- Connection lifecycle --

    async def connect(self, device: LANDevice | None = None) -> ConnectionInfo:
        """Connect to the specified device, or auto-discover one.

        If ``device`` is None and the policy is AUTO or LAN_ONLY, scans
        for LAN devices first.  If none found and a remote adapter exists,
        connects via remote transport.

        Returns the current :class:`ConnectionInfo` after connection.
        """
        async with self._lock:
            if self._connecting:
                raise ConnectivitySessionError("Connection already in progress", code="already_connecting")

            self._connecting = True
            try:
                return await self._connect_impl(device)
            finally:
                self._connecting = False

    async def disconnect(self) -> None:
        """Disconnect and reset to DISCONNECTED state."""
        async with self._lock:
            self.reason = ConnectionReason.MANUAL_DISCONNECT.value
            self.state = ConnectionState.DISCONNECTED

            if self._transport is not None:
                try:
                    await self._transport.close()
                except Exception:  # noqa: BLE001
                    pass
                self._transport = None

            if self._remote_adapter is not None:
                try:
                    await self._remote_adapter.disconnect()
                except Exception:  # noqa: BLE001
                    pass

            self.current_transport = TransportKind.LOCAL
            self.current_device = None
            self._notify_state()

    async def reconnect(self) -> ConnectionInfo:
        """Attempt to reconnect with the previously connected device.

        Falls back to remote transport if LAN is unavailable.
        """
        async with self._lock:
            if self.current_device is not None:
                return await self.connect(self.current_device)
            # Try LAN discovery first.
            devices = await self._scan_devices()
            if devices:
                return await self.connect(devices[0])
            # Fall back to remote.
            return await self._connect_remote()

    # -- Message transport --

    async def send(self, kind: str, payload: dict[str, Any]) -> int:
        """Send a message through the current transport."""
        async with self._lock:
            if self.current_transport == TransportKind.LAN_TLS and self._transport is not None:
                return await self._transport.send(kind, payload)
            elif self._remote_adapter is not None:
                return await self._remote_adapter.send(kind, payload)
            raise ConnectivitySessionError(
                "No active transport to send",
                code="no_transport",
            )

    async def receive(self, timeout: float = 30.0) -> dict[str, Any] | None:
        """Receive one message from the current transport."""
        async with self._lock:
            if self.current_transport == TransportKind.LAN_TLS and self._transport is not None:
                return await self._transport.receive(timeout=timeout)
            elif self._remote_adapter is not None:
                return await self._remote_adapter.receive(timeout=timeout)
            return None

    async def receive_stream(self) -> AsyncIterator[dict[str, Any]]:
        """Stream messages until the connection is lost."""
        while self.state != ConnectionState.DISCONNECTED:
            msg = await self.receive()
            if msg is None:
                break
            yield msg
            for handler in list(self._message_handlers):
                try:
                    await handler(msg)
                except Exception:  # noqa: BLE001
                    logger.exception("Message handler error")

    # -- State management --

    def on_state_change(self, handler: Any) -> None:
        """Register a callback for state changes."""
        self._state_handlers.append(handler)

    def on_message(self, handler: callable) -> None:
        """Register a callback for received messages."""
        self._message_handlers.append(handler)

    def info(self) -> ConnectionInfo:
        """Return a snapshot of the current connection state."""
        return ConnectionInfo(
            device_id=self.current_device.device_id if self.current_device else "",
            transport_kind=self.current_transport,
            state=self.state,
            reason=self.reason,
            endpoint_url=self.current_device.connect_url if self.current_device else "",
            established_at=time.time() if self.state == ConnectionState.CONNECTED else 0.0,
            last_heartbeat_at=self._monitor.last_pong_at if self._monitor else 0.0,
            heartbeat_interval=self.policy.heartbeat_interval,
            heartbeat_timeout=self.policy.heartbeat_timeout,
            reconnect_attempt=0,
            max_reconnect_attempts=self.policy.max_reconnect_attempts,
            remote_address=self.current_device.host if self.current_device else "",
        )

    # -- Internals --

    async def _connect_impl(self, device: LANDevice | None) -> ConnectionInfo:
        if device is None:
            # Auto-discover LAN devices.
            devices = await self._scan_devices()
            if devices:
                device = devices[0]
            elif self.policy.remote_fallback:
                # No LAN devices found, try remote.
                if self.policy.preferred_mode == ConnectivityMode.LAN_ONLY:
                    raise ConnectivitySessionError(
                        "No LAN devices found and mode is LAN_ONLY",
                        code="no_lan_available",
                    )
                return await self._connect_remote()
            else:
                raise ConnectivitySessionError(
                    "No LAN devices found",
                    code="no_devices",
                )

        self.state = ConnectionState.CONNECTING
        self.current_device = device
        self.reason = ConnectionReason.LAN_AVAILABLE.value
        self._notify_state()

        # Build transport config.
        config = TransportConfig.from_lan_device(device)
        self._transport = LANTransport(config)

        try:
            await self._transport.connect()
        except LANTransportError as exc:
            self.state = ConnectionState.ERROR
            self.reason = ConnectionReason.LAN_ERROR.value
            self._notify_state()
            raise ConnectivitySessionError(
                f"LAN connection failed: {exc}",
                code="lan_connect_failed",
            ) from exc

        # If remote fallback is enabled and migration is configured, set it up.
        if self.policy.remote_fallback:
            if self._remote_adapter is None:
                self._remote_adapter = RemoteAdapter()
            if self._migration is None:
                self._migration = LANRemoteMigration(self)
            if self._monitor is None:
                self._monitor = ConnectivityMonitor(self)
                await self._monitor.start()

        self.state = ConnectionState.CONNECTED
        self.current_transport = TransportKind.LAN_TLS
        self.reason = ConnectionReason.LAN_AVAILABLE.value

        # Start monitor for health checks and migration.
        if self._monitor is not None:
            await self._monitor.start()

        self._notify_state()
        return self.info()

    async def _connect_remote(self) -> ConnectionInfo:
        """Connect via remote transport adapter."""
        if self._remote_adapter is None:
            self._remote_adapter = RemoteAdapter()

        self.state = ConnectionState.CONNECTING
        self.reason = ConnectionReason.REMOTE_FALLBACK.value
        self._notify_state()

        try:
            await self._remote_adapter.connect()
        except RemoteAdapterError as exc:
            self.state = ConnectionState.ERROR
            self.reason = ConnectionReason.REMOTE_CONNECTED.value
            self._notify_state()
            raise ConnectivitySessionError(
                f"Remote connection failed: {exc}",
                code="remote_connect_failed",
            ) from exc

        self.state = ConnectionState.CONNECTED
        self.current_transport = TransportKind.REMOTE
        self.reason = ConnectionReason.REMOTE_CONNECTED.value
        self._notify_state()
        return self.info()

    async def _scan_devices(self) -> list[LANDevice]:
        """Scan for LAN devices using the scanner."""
        if self._device_scanner is None:
            self._device_scanner = LANDeviceScanner()
        return self._device_scanner.scan_once()

    def _notify_state(self) -> None:
        for handler in list(self._state_handlers):
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(self.state, self.reason))
                else:
                    handler(self.state, self.reason)
            except Exception:  # noqa: BLE001
                logger.exception("State handler error")

    async def _migrate_to_remote(self, reason: str) -> None:
        """Migrate from LAN to remote transport."""
        if self._migration is None:
            self._migration = LANRemoteMigration(self)
        try:
            await self._migration.migrate_to_remote(reason=reason)
        except Exception:  # noqa: BLE001
            self.state = ConnectionState.ERROR
            self.reason = ConnectionReason.LAN_ERROR.value
            self._notify_state()

    async def _migrate_to_lan(self, device: LANDevice, reason: str) -> None:
        """Migrate from remote to LAN transport."""
        if self._migration is None:
            self._migration = LANRemoteMigration(self)
        try:
            await self._migration.migrate_to_lan(device=device, reason=reason)
        except Exception:  # noqa: BLE001
            self.state = ConnectionState.ERROR
            self.reason = ConnectionReason.LAN_ERROR.value
            self._notify_state()


# Keep backward-compat alias
ConnectionConnectionReason = ConnectionReason


__all__ = [
    "ConnectivitySession",
    "ConnectivitySessionError",
]
