"""Gateway composition without creating a second RuntimeStack or SessionStore."""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

from gateway.service import SlonGateway
from i18n import t


class GatewayConfigurationError(RuntimeError):
    pass


def build_gateway(
    *, repo_root: str | Path, runtime_stack,
    key_provider: Callable[[str], str | None],
) -> SlonGateway:
    root = Path(repo_root).resolve()
    encoded = key_provider("gateway_signing_key")
    if not encoded:
        raise GatewayConfigurationError("gateway_signing_key is required")
    try:
        signing_key = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise GatewayConfigurationError("gateway_signing_key is invalid") from exc
    if len(signing_key) < 32:
        raise GatewayConfigurationError("gateway_signing_key is too short")
    manager = getattr(runtime_stack, "session_manager", None)
    if manager is None:
        raise GatewayConfigurationError(t("error.runtime_stack_required"))
    return SlonGateway(
        database_path=root / "memory" / "slon_gateway.sqlite3",
        artifact_root=root / "memory" / "gateway_artifacts",
        signing_key=signing_key,
        session_manager=manager,
        runtime_stack=runtime_stack,
    )


__all__ = ["GatewayConfigurationError", "build_gateway"]
