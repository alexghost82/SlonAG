"""Conservative files stub — no arbitrary filesystem access.

Paths are checked against an injected allowlist. Denied by default.
Never opens, lists, or mutates real filesystem entries outside the allowlist
callback (callers may inject a read-only enumerator for tests).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from pathlib import PurePosixPath

from server.routes._common import (
    DevicePrincipal,
    RouteResponse,
    error_response,
    require_active_principal,
    sanitize_body,
)
from server.schemas import CODE_UNAUTHORIZED

# Reuse unauthorized-shaped denial for path policy violations when no better
# schema code exists for files (files are not in server.schemas yet).
CODE_FORBIDDEN_PATH = "invalid_request"


def _normalize_path(path: str) -> str:
    raw = path.strip() or "/"
    # Reject Windows drive roots and traversal early.
    lowered = raw.replace("\\", "/").lower()
    if lowered in {"/", "/etc", "/system", "c:/", "c:/windows"} or lowered.startswith(
        ("../", "/../")
    ):
        return raw
    # Collapse duplicate slashes for allowlist comparison.
    parts = [p for p in PurePosixPath(raw.replace("\\", "/")).parts if p not in ("", ".")]
    if not parts:
        return "/"
    if parts[0] == "/":
        return "/" + "/".join(parts[1:])
    return "/".join(parts)


def _is_allowed(path: str, allowlist: Collection[str] | None) -> bool:
    if allowlist is None:
        return False
    normalized = _normalize_path(path)
    allowed = {_normalize_path(item) for item in allowlist}
    if normalized in allowed:
        return True
    # Prefix allow: "/workspace" permits "/workspace/docs"
    for prefix in allowed:
        if prefix != "/" and (
            normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/")
        ):
            return True
    return False


class FilesHandler:
    """List/read stubs gated by an injected allowlist. Default deny."""

    def __init__(
        self,
        *,
        allowlist: Collection[str] | None = None,
        enumerator: Callable[[str], list[dict[str, object]]] | None = None,
    ) -> None:
        self._allowlist = frozenset(allowlist) if allowlist is not None else None
        self._enumerator = enumerator

    def list_entries(
        self,
        *,
        principal: DevicePrincipal | None,
        path: str,
    ) -> RouteResponse:
        denied = require_active_principal(principal)
        if denied is not None:
            return denied

        if not _is_allowed(path, self._allowlist):
            return error_response(
                403,
                CODE_FORBIDDEN_PATH,
                "Path is not on the injected files allowlist.",
                field="path",
            )

        entries: list[dict[str, object]]
        if self._enumerator is not None:
            entries = list(self._enumerator(path))
        else:
            # No FS access — empty listing for allowlisted paths.
            entries = []

        return RouteResponse(
            status_code=200,
            body=sanitize_body(
                {
                    "path": _normalize_path(path),
                    "entries": entries,
                }
            ),
        )

    def mutate_denied(
        self,
        *,
        principal: DevicePrincipal | None,
        body: Mapping[str, object] | None = None,
    ) -> RouteResponse:
        """Mutating file ops are stubbed as hard deny (no FS writes)."""
        del body  # unused; present for future schema alignment
        denied = require_active_principal(principal)
        if denied is not None:
            return denied
        return error_response(
            403,
            CODE_UNAUTHORIZED,
            "File mutations are disabled in the conservative files stub.",
        )


__all__ = ["FilesHandler"]
