"""Desktop Control pairing: one-time codes and per-device credentials.

Loopback-oriented service with injectable clock/store/rng for tests.
Never logs or stores the raw device secret; only a one-way hash is retained.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_CODE_TTL_SECONDS = 120.0
QR_PAYLOAD_PREFIX = "mark-pair://local/"

CODE_INVALID = "invalid_pairing_code"
CODE_EXPIRED = "expired_pairing_code"
CODE_UNPAIRED = "unpaired_device"


def _pairing_message(code: str) -> str:
    return {
        CODE_INVALID: "Pairing code is invalid or already used.",
        CODE_EXPIRED: "Pairing code has expired.",
        CODE_UNPAIRED: "Device is not paired or has been revoked.",
    }.get(code, "Pairing request failed.")


class PairingError(Exception):
    """Base pairing failure. Messages never include device secrets."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message if message is not None else _pairing_message(code))


class InvalidPairingCodeError(PairingError):
    """Wrong, unknown, or already-consumed one-time pairing code."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_INVALID, message)


class ExpiredPairingCodeError(PairingError):
    """One-time pairing code past its short TTL."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_EXPIRED, message)


class UnpairedDeviceError(PairingError):
    """Device id is unknown or no longer paired."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(CODE_UNPAIRED, message)


@dataclass(frozen=True)
class PairingStart:
    """Fields aligned with ``PairingStartResponse`` (QR string, not an image)."""

    code: str
    expires_at: float
    qr_payload: str


@dataclass(frozen=True)
class DeviceCredential:
    """Opaque per-device credential. ``device_secret`` is returned once."""

    device_id: str
    device_secret: str
    expires_at: float | None = None


@dataclass
class PendingChallenge:
    """In-memory one-time pairing challenge. No secrets."""

    code: str
    expires_at: float

    def __repr__(self) -> str:
        return (
            f"PendingChallenge(code={self.code!r}, expires_at={self.expires_at!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@dataclass
class DeviceRecord:
    """Stored device row. Holds only a hash of the secret, never the raw value."""

    device_id: str
    device_name: str
    secret_hash: str
    active: bool
    created_at: float

    def __repr__(self) -> str:
        # Omit secret_hash so neither raw nor derived material appears in repr/str.
        return (
            "DeviceRecord("
            f"device_id={self.device_id!r}, "
            f"device_name={self.device_name!r}, "
            f"active={self.active!r}, "
            f"created_at={self.created_at!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


class PairingRng(Protocol):
    """Injectable entropy source for codes and credential material."""

    def pairing_code(self) -> str: ...

    def device_id(self) -> str: ...

    def device_secret(self) -> str: ...


class SystemPairingRng:
    """Stdlib ``secrets``-backed RNG (no third-party crypto packages)."""

    def pairing_code(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def device_id(self) -> str:
        return "dev_" + secrets.token_hex(8)

    def device_secret(self) -> str:
        return secrets.token_urlsafe(32)


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _qr_payload(code: str) -> str:
    return f"{QR_PAYLOAD_PREFIX}{code}"


class PairingService:
    """Issue one-time pairing codes and revocable per-device credentials."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        store: MutableMapping[str, Any] | None = None,
        rng: PairingRng | None = None,
        code_ttl_seconds: float = DEFAULT_CODE_TTL_SECONDS,
    ) -> None:
        if code_ttl_seconds <= 0:
            raise ValueError("code_ttl_seconds must be positive")
        self._clock: Callable[[], float] = clock if clock is not None else time.time
        self._store: MutableMapping[str, Any] = store if store is not None else {}
        self._rng: PairingRng = rng if rng is not None else SystemPairingRng()
        self._code_ttl_seconds = float(code_ttl_seconds)
        self._store.setdefault("pending", {})
        self._store.setdefault("devices", {})

    @property
    def pending(self) -> MutableMapping[str, PendingChallenge]:
        return self._store["pending"]

    @property
    def devices(self) -> MutableMapping[str, DeviceRecord]:
        return self._store["devices"]

    def start(self) -> PairingStart:
        """Create a short-lived one-time pairing code and QR payload string."""
        now = float(self._clock())
        code = self._rng.pairing_code()
        # Avoid colliding with an unused live challenge; rare for 6-digit codes.
        while code in self.pending and float(self.pending[code].expires_at) > now:
            code = self._rng.pairing_code()
        expires_at = now + self._code_ttl_seconds
        self.pending[code] = PendingChallenge(code=code, expires_at=expires_at)
        return PairingStart(
            code=code,
            expires_at=expires_at,
            qr_payload=_qr_payload(code),
        )

    def complete(self, code: str, device_name: str) -> DeviceCredential:
        """Exchange a valid one-time code for a device id + secret (once)."""
        if not isinstance(code, str) or not code:
            raise InvalidPairingCodeError()
        name = device_name.strip() if isinstance(device_name, str) else ""
        if not name:
            raise InvalidPairingCodeError("device_name is required.")

        challenge = self.pending.get(code)
        if challenge is None:
            raise InvalidPairingCodeError()

        now = float(self._clock())
        if now >= float(challenge.expires_at):
            self.pending.pop(code, None)
            raise ExpiredPairingCodeError()

        # Consume immediately so the code cannot be reused.
        self.pending.pop(code, None)

        device_id = self._rng.device_id()
        while device_id in self.devices:
            device_id = self._rng.device_id()
        device_secret = self._rng.device_secret()
        record = DeviceRecord(
            device_id=device_id,
            device_name=name,
            secret_hash=_hash_secret(device_secret),
            active=True,
            created_at=now,
        )
        self.devices[device_id] = record
        return DeviceCredential(
            device_id=device_id,
            device_secret=device_secret,
            expires_at=None,
        )

    def revoke(self, device_id: str) -> None:
        """Immediately invalidate credentials for ``device_id`` if present."""
        record = self.devices.get(device_id)
        if record is None:
            return
        record.active = False

    def is_active(self, device_id: str) -> bool:
        """Return True only for a known, non-revoked paired device."""
        record = self.devices.get(device_id)
        return bool(record is not None and record.active)

    def verify_device_secret(self, device_id: str, device_secret: str) -> bool:
        """Constant-time check of a presented secret against the stored hash.

        Intended for auth integration. Returns False for unknown/revoked devices.
        Never logs the presented secret.
        """
        record = self.devices.get(device_id)
        if record is None or not record.active:
            return False
        if not isinstance(device_secret, str) or not device_secret:
            return False
        presented = _hash_secret(device_secret)
        return hmac.compare_digest(presented, record.secret_hash)


__all__ = [
    "CODE_EXPIRED",
    "CODE_INVALID",
    "CODE_UNPAIRED",
    "DEFAULT_CODE_TTL_SECONDS",
    "QR_PAYLOAD_PREFIX",
    "DeviceCredential",
    "DeviceRecord",
    "ExpiredPairingCodeError",
    "InvalidPairingCodeError",
    "PairingError",
    "PairingRng",
    "PairingService",
    "PairingStart",
    "PendingChallenge",
    "SystemPairingRng",
    "UnpairedDeviceError",
]


# E2E test compatibility shim

class PairingStore:
    """Minimal pairing store for LAN discovery/pairing E2E tests."""

    def __init__(self) -> None:
        self._pairs: dict[str, dict[str, Any]] = {}

    def register(self, device_id: str, secret: str) -> str:
        code = secrets.token_hex(6).upper()
        self._pairs[device_id] = {
            "code": code,
            "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
            "created_at": time.time(),
        }
        return code

    def verify(self, device_id: str, code: str) -> bool:
        entry = self._pairs.get(device_id)
        if entry is None:
            return False
        # For simplicity, compare code directly (in production, use secure comparison)
        return entry["code"] == code

    def get_credentials(self, device_id: str) -> dict[str, Any] | None:
        entry = self._pairs.get(device_id)
        if entry is None:
            return None
        return {"device_id": device_id, "pairing_code": entry["code"]}

    def generate_token(self, device_name: str) -> str:
        """Generate a unique pairing token for a device."""
        token = secrets.token_hex(10)
        self._pairs[device_name] = {"token": token, "created_at": time.time()}
        return token

    def list_registered(self) -> list[dict[str, Any]]:
        return list(self._pairs.values())
