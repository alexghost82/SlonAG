"""GET /v1/status — desktop health without secrets.

Status now queries real runtime state via the observability module.
No fabricated ``online=True`` / ``paired=True`` — the endpoint
reflects what is actually working at the time of the request.
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


__all__ = ["get_status"]
