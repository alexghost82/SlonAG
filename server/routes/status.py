"""GET /v1/status and /v1/health — desktop health without secrets.

Status queries real runtime state via the observability module.
No fabricated ``online=True`` / ``paired=True``.
Health provides readiness probes without authentication.
"""

from __future__ import annotations

from collections.abc import Callable

from server.routes._common import (
    DevicePrincipal,
    RouteResponse,
    require_active_principal,
    sanitize_body,
)
from server.schemas import StatusResponse


def get_status(
    *,
    principal: DevicePrincipal | None,
    provider: Callable[[], StatusResponse] | None = None,
) -> RouteResponse:
    """Return desktop status for an authenticated, non-revoked principal."""
    denied = require_active_principal(principal)
    if denied is not None:
        return denied

    if provider is not None:
        status = provider()
    else:
        # Real runtime status — no fake defaults.
        from observability.status import get_runtime_status as _real_status

        status = _real_status()

    return RouteResponse(status_code=200, body=sanitize_body(status.to_dict()))


def health_check(
    *,
    is_listening: bool,
    tls_enabled: bool = False,
    bind_host: str = "127.0.0.1",
    bind_port: int = 8765,
    uptime: float = 0.0,
    provider: Callable[[], dict[str, object]] | None = None,
) -> RouteResponse:
    """Return readiness status for a health probe.

    No authentication required — health checks must be callable by
    load-balancers and monitoring systems without credentials.
    """
    if provider is not None:
        extra: dict[str, object] = dict(provider())
    else:
        extra = {}

    body: dict[str, object] = {
        "status": "ok" if is_listening else "starting",
        "uptime_seconds": uptime,
        "tls": tls_enabled,
        "bind_host": bind_host,
        "bind_port": bind_port,
        **extra,
    }

    return RouteResponse(status_code=200, body=sanitize_body(body))


__all__ = ["get_status", "health_check"]
