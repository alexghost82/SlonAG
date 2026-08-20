"""Pinned-device authentication for the Gateway trust boundary."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gateway.store import GatewayStore
from server.auth import (
    DeviceCredential, DevicePrincipal, IssuedTokens, RateLimiter, TokenService,
    _RefreshRecord,
)
from server.pairing import PairingService, PairingStart

PROOF_TTL_SECONDS = 60.0


class GatewayAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceChallenge:
    device_id: str
    nonce: str
    expires_at: float


class GatewayAuthService:
    """One-time pairing followed by Ed25519 possession proof and token rotation."""

    def __init__(
        self, *, store: GatewayStore, signing_key: bytes,
        pairing: PairingService | None = None,
        clock: Callable[[], float] | None = None,
        access_ttl_seconds: float = 900.0,
    ) -> None:
        self.store = store
        self._clock = clock or time.time
        self._pairing = pairing or PairingService(clock=self._clock)
        self._lock = threading.RLock()
        self._pairing_limit = RateLimiter(
            capacity=10, refill_per_second=1 / 12, clock=self._clock
        )
        self._challenge_limit = RateLimiter(
            capacity=8, refill_per_second=1 / 10, clock=self._clock
        )
        self._challenges: dict[str, tuple[str, float]] = {}
        self._tokens = TokenService(
            signing_key=signing_key, clock=self._clock,
            is_revoked=lambda device_id: not self._active(device_id),
            refresh_put=self._put_refresh,
            refresh_pop=self._pop_refresh,
            jti_consume=lambda jti: self.store.consume_access_jti(
                jti, float(self._clock())
            ),
            access_ttl_seconds=access_ttl_seconds,
        )

    def start_pairing(self) -> PairingStart:
        with self._lock:
            if not self._pairing_limit.allow("pairing"):
                raise GatewayAuthError("pairing rate limit exceeded")
            return self._pairing.start()

    def complete_pairing(
        self, *, code: str, device_name: str, public_key: str,
        workspace_id: str,
    ) -> str:
        key_bytes = _decode_public_key(public_key)
        fingerprint = hashlib.sha256(key_bytes).hexdigest()
        with self._lock:
            if not self._pairing_limit.allow("pairing"):
                raise GatewayAuthError("pairing rate limit exceeded")
            credential = self._pairing.complete(code, device_name)
            self.store.trust_device(
                device_id=credential.device_id, device_name=device_name.strip(),
                public_key=public_key, key_fingerprint=fingerprint,
                workspace_id=workspace_id, created_at=float(self._clock()),
            )
        return credential.device_id

    def challenge(self, device_id: str) -> DeviceChallenge:
        if not self._challenge_limit.allow(device_id):
            raise GatewayAuthError("device challenge rate limit exceeded")
        if not self._active(device_id):
            raise GatewayAuthError("device is not trusted")
        nonce = secrets.token_urlsafe(32)
        expires_at = float(self._clock()) + PROOF_TTL_SECONDS
        with self._lock:
            self._challenges[device_id] = (nonce, expires_at)
        return DeviceChallenge(device_id, nonce, expires_at)

    def exchange_proof(
        self, *, device_id: str, nonce: str, signature: str,
    ) -> IssuedTokens:
        with self._lock:
            pending = self._challenges.pop(device_id, None)
        if pending is None or pending[0] != nonce:
            raise GatewayAuthError("device challenge is invalid or already used")
        if float(self._clock()) >= pending[1]:
            raise GatewayAuthError("device challenge expired")
        record = self.store.device(device_id)
        if record is None or not bool(record["active"]):
            raise GatewayAuthError("device is not trusted")
        try:
            public = Ed25519PublicKey.from_public_bytes(
                _decode_public_key(str(record["public_key"]))
            )
            public.verify(_decode_signature(signature), nonce.encode("utf-8"))
        except (InvalidSignature, ValueError) as exc:
            raise GatewayAuthError("device key proof rejected") from exc
        return self._tokens.mint(
            DeviceCredential(device_id=device_id, device_secret="pinned-key"),
            scopes={"gateway.full"},
        )

    def refresh(self, refresh_token: str) -> IssuedTokens:
        return self._tokens.refresh(refresh_token)

    def authenticate(self, headers: dict[str, str]) -> DevicePrincipal:
        return self._tokens.authenticate(headers)

    def authenticate_connection(self, headers: dict[str, str]) -> DevicePrincipal:
        return self._tokens.authenticate(headers, consume_jti=True)

    def validate_connection(self, headers: dict[str, str]) -> DevicePrincipal:
        return self._tokens.authenticate(headers, consume_jti=False)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            self._challenges.pop(device_id, None)
            return self.store.revoke_device(device_id, revoked_at=float(self._clock()))

    def trusted_devices(self, *, workspace_id: str):
        return self.store.list_devices(workspace_id=workspace_id)

    def workspace_for(self, device_id: str) -> str:
        record = self.store.device(device_id)
        if record is None or not bool(record["active"]):
            raise GatewayAuthError("device is not trusted")
        return str(record["workspace_id"])

    def _active(self, device_id: str) -> bool:
        record = self.store.device(device_id)
        return bool(record is not None and record["active"])

    def _put_refresh(self, token_hash: str, record: _RefreshRecord) -> None:
        self.store.put_refresh_token(
            token_hash, device_id=record.device_id, device_name=record.device_name,
            expires_at=record.expires_at, scopes=sorted(record.scopes),
        )

    def _pop_refresh(self, token_hash: str) -> _RefreshRecord | None:
        row = self.store.pop_refresh_token(token_hash)
        if row is None:
            return None
        return _RefreshRecord(
            device_id=str(row["device_id"]),
            device_name=(str(row["device_name"]) if row["device_name"] is not None else None),
            expires_at=float(row["expires_at"]),
            scopes=frozenset(str(value) for value in row["scopes"]),
        )


def _decode_public_key(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise GatewayAuthError("device public key is invalid") from exc
    if len(raw) != 32:
        raise GatewayAuthError("device public key is invalid")
    return raw


def _decode_signature(value: str) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise GatewayAuthError("device signature is invalid") from exc
    if len(raw) != 64:
        raise GatewayAuthError("device signature is invalid")
    return raw


__all__ = ["DeviceChallenge", "GatewayAuthError", "GatewayAuthService"]
