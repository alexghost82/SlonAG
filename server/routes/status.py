"""GET /v1/status — desktop health without secrets."""

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


__all__ = ["get_status"]
