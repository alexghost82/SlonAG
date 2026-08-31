"""Core types for the Slon Connectivity architecture.

Defines transport kinds, connection states, and the types used by every
sub-component (discovery, identity, session, monitor, migration).

This module has no side-effects and does not import network libraries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# ---------------------------------------------------------------------------
# Transport kinds
# ---------------------------------------------------------------------------

class TransportKind(StrEnum):
    """Which physical/protocol channel carries the traffic."""

    LAN_TLS = "lan_tls"          # direct WebSocket-over-TLS on same LAN
    LAN_WS = "lan_ws"            # direct WebSocket (plain TCP) on same LAN
    REMOTE = "remote"            # remoted through a transport adapter
    LOCAL = "local"              # in-process / loopback (desktop ↔ UI)


class ConnectivityMode(StrEnum):
    """Policy for selecting a transport at connection time."""

    AUTO = "auto"                # LAN first, then remote
    LAN_ONLY = "lan_only"        # fail if no LAN reachable
    REMOTE_ONLY = "remote_only"  # always use remote


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------

class ConnectionState(StrEnum):
    """Observable connection state. Always monotonically progresses except on
    explicit disconnect."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    MIGRATING = "migrating"
    ERROR = "error"


class ConnectionReason(StrEnum):
    """Why the current state changed (populates ``reason``)."""

    MANUAL_DISCONNECT = "manual_disconnect"
    LAN_AVAILABLE = "lan_available"
    LAN_LOST = "lan_lost"
    LAN_RESTORED = "lan_restored"
    LAN_ERROR = "lan_error"
    REMOTE_FALLBACK = "remote_fallback"
    REMOTE_CONNECTED = "remote_connected"
    MIGRATION_SUCCESS = "migration_success"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    CERTIFICATE_ERROR = "certificate_error"
    AUTH_FAILED = "auth_failed"
    SERIALIZATION_ERROR = "serialization_error"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceIdentity:
    """Opaque device identity (generated once per device)."""

    device_id: str
    display_name: str
    public_key_pem: str
    fingerprint_sha256: str
    created_at: float
    model: str = ""
    os_name: str = ""
    os_version: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def generate(display_name: str, **kwargs: Any) -> "DeviceIdentity":
        import os, platform
        import time
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fp_hash = hashlib.sha256(public_pem).hexdigest()[:16]
        device_id = f"dev-{uuid.uuid4().hex[:12]}"
        return DeviceIdentity(
            device_id=device_id,
            display_name=display_name,
            public_key_pem=public_pem.decode("utf-8").strip(),
            fingerprint_sha256=fp_hash,
            created_at=time.time(),
            model=kwargs.get("model", ""),
            os_name=kwargs.get("os_name", platform.system() or ""),
            os_version=kwargs.get("os_version", platform.release() or ""),
            extra=kwargs.get("extra", {}),
        )


@dataclass(frozen=True)
class CertificateInfo:
    """Parsed server certificate metadata (no secrets)."""

    common_name: str
    subject: str
    issuer: str
    not_before: float
    not_after: float
    san_dns: list[str]
    san_ip: list[str]
    valid: bool


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscoveredDevice:
    """A device found via discovery (Bonjour/mDNS)."""

    host: str
    port: int
    device_id: str
    display_name: str
    fingerprint: str
    service_type: str = "_mark-control._tcp.local."
    properties: dict[str, str] = field(default_factory=dict)
    discovered_at: float = field(default_factory=lambda: 0.0)

    def __post_init__(self) -> None:
        if self.discovered_at == 0.0:
            import time
            object.__setattr__(self, "discovered_at", time.time())


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

@dataclass
class TransportEndpoint:
    """Logical endpoint for a transport."""

    kind: TransportKind
    url: str
    host: str
    port: int
    device_id: str = ""
    certificate_pem: str = ""
    verify_certificate: bool = True


@dataclass
class TransportSession:
    """Handle returned by a successful transport connect."""

    endpoint: TransportEndpoint
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    established_at: float = field(default_factory=lambda: __import__("time").time())


@dataclass
class TransportMessage:
    """Message sent/received over a transport."""

    kind: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@dataclass
class ConnectionInfo:
    """Full snapshot of a logical connection for the UI or tests."""

    device_id: str
    transport_kind: TransportKind
    state: ConnectionState
    reason: str = ""
    endpoint_url: str = ""
    established_at: float = 0.0
    last_heartbeat_at: float = 0.0
    heartbeat_interval: float = 15.0
    heartbeat_timeout: float = 45.0
    reconnect_attempt: int = 0
    max_reconnect_attempts: int = 5
    session_id: str = ""
    remote_address: str = ""
    certificate_valid: bool = True


@dataclass
class MigrationEvent:
    """Signifies a transport switch (LAN→remote or remote→LAN)."""

    from_kind: TransportKind
    to_kind: TransportKind
    reason: str
    session_id: str
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# ---------------------------------------------------------------------------
# Backward compat alias for ConnectionReason
ConnectionConnectionReason = ConnectionReason

# Policy
# ---------------------------------------------------------------------------

@dataclass
class ConnectivityPolicy:
    """User-configurable connectivity preferences."""

    preferred_mode: ConnectivityMode = ConnectivityMode.AUTO
    lan_preferred: bool = True
    remote_fallback: bool = True
    auto_reconnect: bool = True
    heartbeat_interval: float = 15.0
    heartbeat_timeout: float = 45.0
    max_reconnect_attempts: int = 5
    lan_reconnect_delay: float = 5.0
    certificate_verify: bool = True
    prefer_secure: bool = True       # TLS before plain WS
    remote_adapter: str = "firebase"  # pluggable adapter name


__all__ = [
    "ConnectivityMode",
    "ConnectivityPolicy",
    "ConnectionConnectionReason",
    "ConnectionState",
    "CertificateInfo",
    "ConnectionInfo",
    "ConnectionReason",
    "DeviceIdentity",
    "DiscoveredDevice",
    "MigrationEvent",
    "TransportEndpoint",
    "TransportKind",
    "TransportMessage",
    "TransportSession",
]
