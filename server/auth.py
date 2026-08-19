"""Per-device access/refresh tokens, auth checks, and in-memory rate limits.

Uses only the standard library (hmac / hashlib / secrets / json / base64).
Never returns AI provider API keys. Never logs raw refresh secrets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Mapping, MutableMapping, MutableSet
from dataclasses import dataclass, field
from typing import Any

DEFAULT_ACCESS_TTL_SECONDS = 900.0
DEFAULT_REFRESH_TTL_SECONDS = 2_592_000.0  # 30 days
TOKEN_TYPE_BEARER = "Bearer"

CODE_UNAUTHORIZED = "unauthorized"
CODE_EXPIRED = "expired"
CODE_REVOKED = "revoked"
CODE_REPLAY = "replay"
CODE_RATE_LIMITED = "rate_limited"
CODE_INVALID_TOKEN = "invalid_token"

Clock = Callable[[], float]
RevocationCheck = Callable[[str], bool]


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _redact_secrets(message: str) -> str:
    """Strip key-like and bearer material from error text."""
    import re

    patterns = (
        re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
        re.compile(r"AIza[A-Za-z0-9_-]{8,}"),
        re.compile(r"(?i)(?:api[_-]?key|token|secret|password|refresh)\s*[:=]\s*\S+"),
        re.compile(r"(?i)Bearer\s+\S+"),
        re.compile(r"(?i)mk_[A-Za-z0-9_-]{8,}"),
        re.compile(r"(?i)rt_[A-Za-z0-9_-]{8,}"),
    )
    redacted = message
    for pattern in patterns:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class AuthError(Exception):
    """Authentication or token failure. Messages never include raw secrets."""

    def __init__(self, message: str, *, code: str = CODE_UNAUTHORIZED) -> None:
        safe = _redact_secrets(message)
        super().__init__(safe)
        self.code = code
        self.message = safe

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"AuthError(code={self.code!r}, message={self.message!r})"


@dataclass(frozen=True)
class DeviceCredential:
    """Opaque per-device credential issued by pairing (returned once)."""

    device_id: str
    device_secret: str
    device_name: str | None = None

    def __repr__(self) -> str:
        return (
            f"DeviceCredential(device_id={self.device_id!r}, "
            f"device_secret='***', device_name={self.device_name!r})"
        )


@dataclass(frozen=True)
class DevicePrincipal:
    """Authenticated device identity derived from a valid access token."""

    device_id: str
    device_name: str | None = None
    jti: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    def __repr__(self) -> str:
        return (
            f"DevicePrincipal(device_id={self.device_id!r}, "
            f"device_name={self.device_name!r}, jti={self.jti!r}, "
            f"scopes={sorted(self.scopes)!r})"
        )


@dataclass(frozen=True)
class IssuedTokens:
    """Access + refresh pair. Treat refresh_token as secret material."""

    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = TOKEN_TYPE_BEARER
    device_id: str = ""
    jti: str = ""

    def to_public_dict(self) -> dict[str, object]:
        """Public mint response — includes tokens for the client, never API keys."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "device_id": self.device_id,
        }

    def __repr__(self) -> str:
        return (
            f"IssuedTokens(device_id={self.device_id!r}, expires_at={self.expires_at!r}, "
            f"token_type={self.token_type!r}, access_token='***', refresh_token='***', "
            f"jti={self.jti!r})"
        )


@dataclass
class _RefreshRecord:
    device_id: str
    device_name: str | None
    expires_at: float
    scopes: frozenset[str]


class TokenService:
    """Mint/verify short-lived HMAC access tokens and rotate refresh tokens."""

    def __init__(
        self,
        *,
        signing_key: bytes | str,
        clock: Clock | None = None,
        access_ttl_seconds: float = DEFAULT_ACCESS_TTL_SECONDS,
        refresh_ttl_seconds: float = DEFAULT_REFRESH_TTL_SECONDS,
        is_revoked: RevocationCheck | MutableSet[str] | None = None,
        used_jtis: MutableSet[str] | None = None,
        used_nonces: MutableSet[str] | None = None,
    ) -> None:
        if isinstance(signing_key, str):
            key = signing_key.encode("utf-8")
        else:
            key = signing_key
        if not key:
            raise ValueError("signing_key must be non-empty")
        self._signing_key = key
        self._clock: Clock = clock if clock is not None else time.time
        self._access_ttl = float(access_ttl_seconds)
        self._refresh_ttl = float(refresh_ttl_seconds)
        self._is_revoked = _normalize_revocation(is_revoked)
        self._used_jtis: MutableSet[str] = used_jtis if used_jtis is not None else set()
        self._used_nonces: MutableSet[str] = (
            used_nonces if used_nonces is not None else set()
        )
        self._refresh_by_hash: MutableMapping[str, _RefreshRecord] = {}

    def mint(
        self,
        credential: DeviceCredential,
        *,
        scopes: frozenset[str] | set[str] | None = None,
        nonce: str | None = None,
        jti: str | None = None,
    ) -> IssuedTokens:
        """Mint a short-lived access token (+ refresh) from a device credential."""
        self._reject_if_revoked(credential.device_id)
        if not credential.device_id or not credential.device_secret:
            raise AuthError("invalid device credential", code=CODE_UNAUTHORIZED)
        self._consume_nonce(nonce)
        scope_set = frozenset(scopes) if scopes is not None else frozenset()
        return self._issue(
            device_id=credential.device_id,
            device_name=credential.device_name,
            scopes=scope_set,
            jti=jti,
        )

    def refresh(
        self,
        refresh_token: str,
        *,
        nonce: str | None = None,
        jti: str | None = None,
    ) -> IssuedTokens:
        """Rotate refresh: old token is invalidated; a new pair is returned."""
        if not refresh_token or not isinstance(refresh_token, str):
            raise AuthError("invalid refresh token", code=CODE_INVALID_TOKEN)
        self._consume_nonce(nonce)
        token_hash = _hash_secret(refresh_token)
        record = self._refresh_by_hash.pop(token_hash, None)
        if record is None:
            raise AuthError("refresh token rejected", code=CODE_INVALID_TOKEN)
        now = float(self._clock())
        if record.expires_at <= now:
            raise AuthError("refresh token expired", code=CODE_EXPIRED)
        self._reject_if_revoked(record.device_id)
        return self._issue(
            device_id=record.device_id,
            device_name=record.device_name,
            scopes=record.scopes,
            jti=jti,
        )

    def verify_access(
        self,
        access_token: str,
        *,
        nonce: str | None = None,
        consume_jti: bool = True,
    ) -> DevicePrincipal:
        """Validate an access token and return a principal."""
        claims = self._parse_and_verify(access_token)
        if claims.get("typ") != "access":
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN)
        device_id = claims.get("did")
        if not isinstance(device_id, str) or not device_id:
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN)
        self._reject_if_revoked(device_id)
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)):
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN)
        if float(exp) <= float(self._clock()):
            raise AuthError("access token expired", code=CODE_EXPIRED)
        token_jti = claims.get("jti")
        if isinstance(token_jti, str) and token_jti:
            if consume_jti:
                self._consume_jti(token_jti)
        self._consume_nonce(nonce)
        name = claims.get("name")
        device_name = name if isinstance(name, str) else None
        raw_scopes = claims.get("scp")
        scopes: frozenset[str]
        if isinstance(raw_scopes, list) and all(isinstance(s, str) for s in raw_scopes):
            scopes = frozenset(raw_scopes)
        else:
            scopes = frozenset()
        return DevicePrincipal(
            device_id=device_id,
            device_name=device_name,
            jti=token_jti if isinstance(token_jti, str) else None,
            scopes=scopes,
        )

    def authenticate(
        self,
        headers: Mapping[str, str],
        *,
        nonce: str | None = None,
        consume_jti: bool = False,
    ) -> DevicePrincipal:
        """Extract Bearer access token from headers and authenticate."""
        token = _extract_bearer(headers)
        return self.verify_access(token, nonce=nonce, consume_jti=consume_jti)

    def _issue(
        self,
        *,
        device_id: str,
        device_name: str | None,
        scopes: frozenset[str],
        jti: str | None,
    ) -> IssuedTokens:
        self._reject_if_revoked(device_id)
        now = float(self._clock())
        jti_provided = jti is not None
        access_jti = jti if jti_provided else secrets.token_urlsafe(16)
        if not access_jti:
            raise AuthError("empty jti rejected", code=CODE_REPLAY)
        if jti_provided:
            # Replay hook: caller-supplied jti may be used only once.
            self._consume_jti(access_jti)
        expires_at = now + self._access_ttl
        claims: dict[str, Any] = {
            "typ": "access",
            "did": device_id,
            "iat": now,
            "exp": expires_at,
            "jti": access_jti,
            "scp": sorted(scopes),
        }
        if device_name is not None:
            claims["name"] = device_name
        access_token = self._sign_claims(claims)
        refresh_raw = "rt_" + secrets.token_urlsafe(32)
        refresh_expires = now + self._refresh_ttl
        self._refresh_by_hash[_hash_secret(refresh_raw)] = _RefreshRecord(
            device_id=device_id,
            device_name=device_name,
            expires_at=refresh_expires,
            scopes=scopes,
        )
        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_raw,
            expires_at=expires_at,
            token_type=TOKEN_TYPE_BEARER,
            device_id=device_id,
            jti=access_jti,
        )

    def _sign_claims(self, claims: Mapping[str, Any]) -> str:
        payload = _b64url_encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        sig = _b64url_encode(
            hmac.new(self._signing_key, payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"mk_{payload}.{sig}"

    def _parse_and_verify(self, token: str) -> dict[str, Any]:
        if not token or not isinstance(token, str):
            raise AuthError("missing access token", code=CODE_UNAUTHORIZED)
        if not token.startswith("mk_"):
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN)
        body = token[3:]
        try:
            payload_b64, sig_b64 = body.split(".", 1)
        except ValueError as exc:
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN) from exc
        expected = _b64url_encode(
            hmac.new(
                self._signing_key, payload_b64.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(expected, sig_b64):
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN)
        try:
            raw = _b64url_decode(payload_b64)
            claims = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN) from exc
        if not isinstance(claims, dict):
            raise AuthError("invalid access token", code=CODE_INVALID_TOKEN)
        return claims

    def _reject_if_revoked(self, device_id: str) -> None:
        if self._is_revoked(device_id):
            raise AuthError("device revoked", code=CODE_REVOKED)

    def _consume_nonce(self, nonce: str | None) -> None:
        if nonce is None:
            return
        if not nonce:
            raise AuthError("empty nonce rejected", code=CODE_REPLAY)
        if nonce in self._used_nonces:
            raise AuthError("replayed nonce rejected", code=CODE_REPLAY)
        self._used_nonces.add(nonce)

    def _consume_jti(self, jti: str) -> None:
        if jti in self._used_jtis:
            raise AuthError("replayed jti rejected", code=CODE_REPLAY)
        self._used_jtis.add(jti)


def authenticate(
    headers: Mapping[str, str],
    *,
    token_service: TokenService,
    nonce: str | None = None,
    consume_jti: bool = False,
) -> DevicePrincipal:
    """Authenticate request headers using an injected TokenService."""
    return token_service.authenticate(headers, nonce=nonce, consume_jti=consume_jti)


class RateLimiter:
    """In-memory token-bucket rate limiter with an injectable clock."""

    def __init__(
        self,
        *,
        capacity: float,
        refill_per_second: float,
        clock: Clock | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_second < 0:
            raise ValueError("refill_per_second must be non-negative")
        self._capacity = float(capacity)
        self._refill = float(refill_per_second)
        self._clock: Clock = clock if clock is not None else time.time
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, cost: float = 1.0) -> bool:
        """Return True and consume ``cost`` tokens if the bucket has room."""
        if cost < 0:
            raise ValueError("cost must be non-negative")
        now = float(self._clock())
        tokens, last = self._buckets.get(key, (self._capacity, now))
        elapsed = max(0.0, now - last)
        tokens = min(self._capacity, tokens + elapsed * self._refill)
        if tokens < cost:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - cost, now)
        return True

    def check(self, key: str, cost: float = 1.0) -> None:
        """Raise AuthError when the key exceeds the rate limit."""
        if not self.allow(key, cost=cost):
            raise AuthError("rate limit exceeded", code=CODE_RATE_LIMITED)


def _normalize_revocation(
    is_revoked: RevocationCheck | MutableSet[str] | None,
) -> RevocationCheck:
    if is_revoked is None:
        return lambda _device_id: False
    if callable(is_revoked):
        return is_revoked
    revoked_set = is_revoked

    def _check(device_id: str) -> bool:
        return device_id in revoked_set

    return _check


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_bearer(headers: Mapping[str, str]) -> str:
    auth = None
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth = value
            break
    if auth is None or not str(auth).strip():
        raise AuthError("pairing or authentication is required", code=CODE_UNAUTHORIZED)
    text = str(auth).strip()
    lower = text.lower()
    if lower.startswith("bearer "):
        token = text[7:].strip()
        if not token:
            raise AuthError("pairing or authentication is required", code=CODE_UNAUTHORIZED)
        return token
    # Accept raw token only when it looks like our access token prefix.
    if text.startswith("mk_"):
        return text
    raise AuthError("pairing or authentication is required", code=CODE_UNAUTHORIZED)


__all__ = [
    "CODE_EXPIRED",
    "CODE_INVALID_TOKEN",
    "CODE_RATE_LIMITED",
    "CODE_REPLAY",
    "CODE_REVOKED",
    "CODE_UNAUTHORIZED",
    "DEFAULT_ACCESS_TTL_SECONDS",
    "DEFAULT_REFRESH_TTL_SECONDS",
    "TOKEN_TYPE_BEARER",
    "AuthError",
    "DeviceCredential",
    "DevicePrincipal",
    "IssuedTokens",
    "RateLimiter",
    "TokenService",
    "authenticate",
]
