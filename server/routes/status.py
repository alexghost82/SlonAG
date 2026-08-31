"""GET /v1/status and /v1/health — desktop health without secrets."""

from __future__ import annotations

import time
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
        status = StatusResponse(
            online=True,
            paired=True,
            provider_id="local",
            model_id="mock-model",
            network_mode="offline",
            privacy_profile="fully_local",
            active_tasks=0,
            pending_approvals=0,
        )
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
