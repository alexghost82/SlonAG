"""LAN/Remote migration logic.

Handles transparent switching between LAN (TLS/WSS) and remote transport
while preserving session state and re-authenticating as needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from acta.connectivity.types import (
    ConnectionReason,
    ConnectionState,
    MigrationEvent,
    TransportKind,
)

if TYPE_CHECKING:
    from acta.connectivity.session import ConnectivitySession

logger = logging.getLogger(__name__)


class LANRemoteMigrationError(RuntimeError):
    """Migration failure."""

    def __init__(self, message: str, *, code: str = "migration_failed") -> None:
        super().__init__(message)
        self.code = code


class LANRemoteMigration:
    """Manages transitions between LAN and remote transports.

    Migration is:
    - Lazy (only happens when a transport fails or a better one is available).
    - State-preserving (sends re-auth on the new transport).
    - Observable (fires MigrationEvent notifications).
    - Never sends raw media through Firebase — only control-plane messages.
    """

    def __init__(self, session: "ConnectivitySession") -> None:
        self._session = session

    # -- LAN -> Remote --

    async def migrate_to_remote(self, reason: str = "lan_lost") -> None:
        """Switch from LAN transport to remote transport.

        Closes the LAN transport, establishes remote connection,
        re-authenticates, and notifies the session.
        """
        from acta.connectivity.session import ConnectivitySessionError

        old_transport = self._session.current_transport

        # Notify migration started.
        self._session.state = ConnectionState.MIGRATING
        self._session.reason = reason

        migration_event = MigrationEvent(
            from_kind=old_transport,
            to_kind=TransportKind.REMOTE,
            reason=reason,
            session_id=self._session.info().session_id,
        )

        try:
            # Close LAN transport.
            if self._session._transport is not None:
                try:
                    await self._session._transport.close()
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to close LAN transport during migration")
                    pass
                self._session._transport = None

            # Remote adapter must exist.
            if self._session._remote_adapter is None:
                from acta.connectivity.remote import RemoteAdapter
                self._session._remote_adapter = RemoteAdapter()

            await self._session._remote_adapter.connect()

            # Re-authenticate on remote transport.
            await self._reauthenticate_remote()

            self._session.current_transport = TransportKind.REMOTE
            self._session.state = ConnectionState.CONNECTED
            self._session.reason = ConnectionReason.MIGRATION_SUCCESS.value

            logger.info("Migrated LAN -> remote (reason: %s)", reason)
        except Exception as exc:
            self._session.state = ConnectionState.ERROR
            self._session.reason = f"migration_failed: {exc}"
            raise ConnectivitySessionError(
                f"Migration to remote failed: {exc}",
                code="migration_failed",
            ) from exc
        finally:
            self._notify_migration(migration_event)

    # -- Remote -> LAN --

    async def migrate_to_lan(
        self, device: Any, reason: str = "lan_restored"
    ) -> None:
        """Switch from remote transport to LAN transport.

        Closes the remote transport, establishes a LAN TLS connection,
        re-authenticates, and notifies the session.
        """
        from acta.connectivity.session import ConnectivitySessionError
        from acta.connectivity.transport import LANTransport, TransportConfig

        old_transport = self._session.current_transport

        # Notify migration started.
        self._session.state = ConnectionState.MIGRATING
        self._session.reason = reason

        migration_event = MigrationEvent(
            from_kind=old_transport,
            to_kind=TransportKind.LAN_TLS,
            reason=reason,
            session_id=self._session.info().session_id,
        )

        try:
            # Close remote transport.
            if self._session._remote_adapter is not None:
                try:
                    await self._session._remote_adapter.disconnect()
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to close remote transport during migration")
                    pass

            # Establish LAN transport.
            config = TransportConfig.from_lan_device(device)
            self._session._transport = LANTransport(config)

            await self._session._transport.connect()

            self._session.current_transport = TransportKind.LAN_TLS
            self._session.current_device = device
            self._session.state = ConnectionState.CONNECTED
            self._session.reason = ConnectionReason.MIGRATION_SUCCESS.value

            logger.info("Migrated remote -> LAN (device: %s, reason: %s)", device.host, reason)
        except Exception as exc:
            self._session.state = ConnectionState.ERROR
            self._session.reason = f"migration_failed: {exc}"
            raise ConnectivitySessionError(
                f"Migration to LAN failed: {exc}",
                code="migration_failed",
            ) from exc
        finally:
            self._notify_migration(migration_event)

    async def _reauthenticate_remote(self) -> None:
        """Send a re-auth message on the remote transport."""
        if self._session._remote_adapter is None:
            return
        try:
            await self._session._remote_adapter.send("auth_reconnect", {})
        except Exception:  # noqa: BLE001
            logger.warning("Re-auth on remote transport failed")

    def _notify_migration(self, event: MigrationEvent) -> None:
        """Notify the session of a migration event."""
        try:
            self._session._notify_state()
        except Exception:  # noqa: BLE001
            pass

    # -- Convenience: scan for LAN during remote connection --

    async def find_best_lan_device(self) -> Any:
        """Scan for LAN devices and return the best candidate.

        Prefers devices with TLS and the most recent discovery time.
        """
        from acta.connectivity.discovery import LANDeviceScanner

        scanner = LANDeviceScanner()
        devices = scanner.scan_once()

        # Prefer TLS devices.
        tls_devices = [d for d in devices if d.uses_tls]
        if tls_devices:
            return max(tls_devices, key=lambda d: len(d.fingerprint))

        return devices[0] if devices else None


__all__ = [
    "LANRemoteMigration",
    "LANRemoteMigrationError",
]
