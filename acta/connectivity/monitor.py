"""Connection health monitoring.

Monitors connection health via heartbeats, handles auto-reconnect,
and detects stale connections. Triggers LAN/remote migration when
a LAN device becomes available while connected via remote.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from acta.connectivity.types import (
    ConnectionReason,
    ConnectionState,
    TransportKind,
)

if TYPE_CHECKING:
    from acta.connectivity.session import ConnectivitySession

logger = logging.getLogger(__name__)


class ConnectivityMonitor:
    """Monitors connection health and manages auto-reconnect + migration.

    Runs a background task that:
    - Sends heartbeats at regular intervals.
    - Detects stale connections (no pong within timeout).
    - Auto-reconnects when the connection drops.
    - Discovers LAN devices while on remote transport.
    """

    def __init__(self, session: "ConnectivitySession") -> None:
        self._session = session
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_pong_at: float = time.monotonic()
        self._reconnect_attempt: int = 0
        self._connected: bool = False

    @property
    def last_pong_at(self) -> float:
        return self._last_pong_at

    async def start(self) -> None:
        """Start the monitoring loop."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def record_pong(self) -> None:
        """Record that a pong was received."""
        self._last_pong_at = time.monotonic()

    # -- Heartbeat --

    async def ping(self) -> bool:
        """Send a ping through the current transport."""
        if self._session._transport is not None and self._session._transport.connected:
            try:
                result = await asyncio.wait_for(
                    self._session._transport.ping(),
                    timeout=5.0,
                )
                if result:
                    self.record_pong()
                return result
            except Exception:  # noqa: BLE001
                return False
        elif self._session._remote_adapter is not None:
            try:
                await self._session._remote_adapter.send("ping", {})
                self.record_pong()
                return True
            except Exception:  # noqa: BLE001
                return False
        return False

    def is_stale(self, max_age: float | None = None) -> bool:
        """Return True if the connection appears stale."""
        if not self._connected:
            return True
        elapsed = time.monotonic() - self._last_pong_at
        limit = max_age or self._session.policy.heartbeat_timeout
        return elapsed > limit

    # -- Internal monitoring loop --

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        try:
            while not self._stop.is_set():
                await self._check_connection()

                # Check heartbeat interval.
                interval = self._session.policy.heartbeat_interval
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=min(interval, 5.0),
                    )
                    break  # stop requested
                except asyncio.TimeoutError:
                    pass

                # Send heartbeat.
                if self._connected:
                    try:
                        await self.ping()
                    except Exception:  # noqa: BLE001
                        pass

                # Check for LAN discovery if on remote.
                if self._session.current_transport == TransportKind.REMOTE:
                    await self._discover_lan_while_remote()

        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Monitor loop error")
        finally:
            self._connected = False

    async def _check_connection(self) -> None:
        """Check if the current transport is still alive."""
        if self._session.state in (
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.MIGRATING,
        ):
            return

        self._connected = self._session.state == ConnectionState.CONNECTED

        if self._connected and self.is_stale():
            logger.warning("Connection appears stale, attempting reconnect")
            self._session.state = ConnectionState.CONNECTING
            self._session.reason = ConnectionReason.HEARTBEAT_TIMEOUT.value
            self._session._notify_state()
            await self._attempt_reconnect()

    async def _attempt_reconnect(self) -> None:
        """Attempt to reconnect using the current device or scan."""
        max_attempts = self._session.policy.max_reconnect_attempts

        for attempt in range(1, max_attempts + 1):
            self._reconnect_attempt = attempt
            logger.info("Reconnect attempt %d/%d", attempt, max_attempts)

            if self._session.current_device is not None:
                try:
                    await self._session.connect(self._session.current_device)
                    self._reconnect_attempt = 0
                    self._connected = True
                    return
                except Exception:  # noqa: BLE001
                    logger.warning("Reconnect attempt %d failed", attempt)
            else:
                try:
                    await self._session.connect()
                    self._reconnect_attempt = 0
                    self._connected = True
                    return
                except Exception:  # noqa: BLE001
                    logger.warning("Reconnect attempt %d failed", attempt)

            # Delay before next attempt.
            delay = self._session.policy.lan_reconnect_delay
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                return  # stop requested during delay
            except asyncio.TimeoutError:
                pass

        # All attempts failed.
        self._session.state = ConnectionState.ERROR
        self._session.reason = ConnectionReason.LAN_ERROR.value
        self._session._notify_state()

    async def _discover_lan_while_remote(self) -> None:
        """Scan for LAN devices while connected via remote transport.

        If a LAN device is found, initiate migration.
        """
        from acta.connectivity.discovery import LANDeviceScanner

        scanner = LANDeviceScanner()
        try:
            devices = scanner.scan_once()
        except Exception:  # noqa: BLE001
            return

        if devices:
            # Prefer TLS devices with fingerprints.
            best = max(
                devices,
                key=lambda d: (1 if d.uses_tls else 0, len(d.fingerprint)),
            )
            if best.uses_tls:
                logger.info(
                    "LAN device found while on remote: %s:%d",
                    best.host,
                    best.port,
                )
                if self._session._migration is None:
                    from acta.connectivity.migration import LANRemoteMigration
                    self._session._migration = LANRemoteMigration(self._session)
                try:
                    await self._session._migration.migrate_to_lan(
                        device=best, reason=ConnectionReason.LAN_RESTORED.value
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("LAN migration failed")


__all__ = [
    "ConnectivityMonitor",
]
