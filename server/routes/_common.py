"""Shared in-process route helpers.

Auth is injected via ``DevicePrincipal``. These helpers never open sockets,
read ``api_keys.json``, or execute desktop tools.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Mapping

from server.schemas import (
    CODE_IDEMPOTENCY_CONFLICT,
    CODE_UNAUTHORIZED,
    ApiError,
    SchemaValidationError,
    strip_secret_fields,
)


@dataclass(frozen=True)
class DevicePrincipal:
    """Minimal paired-device identity for route handlers.

    Real token validation lives in ``server.auth`` (injected later).
    """

    device_id: str
    revoked: bool = False


@dataclass(frozen=True)
class RouteResponse:
    """In-process HTTP-like response.

    JSON handlers set ``body``. Binary handlers may set ``raw_body`` with
    ``content_type`` (``body`` stays empty or metadata-only).
    """

    status_code: int
    body: dict[str, object]
    raw_body: bytes | None = None
    content_type: str | None = None


def error_response(
    status_code: int,
    code: str,
    message: str | None = None,
    *,
    field: str | None = None,
) -> RouteResponse:
    error = ApiError.of(code, message)
    body: dict[str, object] = {"error": error.to_dict()}
    if field is not None:
        body["field"] = field
    return RouteResponse(status_code=status_code, body=body)


def require_active_principal(
    principal: DevicePrincipal | None,
) -> RouteResponse | None:
    """Return 401/403 error if principal is missing or revoked; else ``None``."""
    if principal is None:
        return error_response(401, CODE_UNAUTHORIZED)
    if principal.revoked:
        return error_response(
            403,
            CODE_UNAUTHORIZED,
            "Device credential has been revoked.",
        )
    return None


def sanitize_body(body: Mapping[str, object]) -> dict[str, object]:
    """Drop known AI key field names from response bodies."""
    return strip_secret_fields(body)


class IdempotencyStore:
    """In-memory idempotency cache for mutating route handlers."""

    def __init__(self) -> None:
        self._responses: dict[str, RouteResponse] = {}
        self._fingerprints: dict[str, dict[str, object]] = {}
        self._side_effects: dict[str, int] = {}

    def side_effect_count(self, key: str) -> int:
        return self._side_effects.get(key, 0)

    def run(
        self,
        *,
        idempotency_key: str,
        fingerprint: Mapping[str, object],
        side_effect_key: str,
        factory: Callable[[], RouteResponse],
    ) -> RouteResponse:
        cached = self._responses.get(idempotency_key)
        if cached is not None:
            prior = self._fingerprints[idempotency_key]
            if prior != dict(fingerprint):
                return error_response(
                    409,
                    CODE_IDEMPOTENCY_CONFLICT,
                )
            return RouteResponse(
                status_code=cached.status_code,
                body=deepcopy(cached.body),
            )

        response = factory()
        sanitized = RouteResponse(
            status_code=response.status_code,
            body=sanitize_body(response.body),
        )
        self._responses[idempotency_key] = sanitized
        self._fingerprints[idempotency_key] = dict(fingerprint)
        self._side_effects[side_effect_key] = (
            self._side_effects.get(side_effect_key, 0) + 1
        )
        return RouteResponse(
            status_code=sanitized.status_code,
            body=deepcopy(sanitized.body),
        )


def schema_error_response(exc: SchemaValidationError) -> RouteResponse:
    return error_response(400, exc.code, str(exc), field=exc.field)


__all__ = [
    "DevicePrincipal",
    "IdempotencyStore",
    "RouteResponse",
    "error_response",
    "require_active_principal",
    "sanitize_body",
    "schema_error_response",
]
