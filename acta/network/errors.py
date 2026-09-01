"""Structured NetworkPolicy error codes.

Messages must never include API keys, tokens, passwords, URLs with
credentials, or other secret values.
"""

from __future__ import annotations

from i18n import t

CODE_OK = "ok"
CODE_OFFLINE = "offline"
CODE_TOOL_NOT_ALLOWED = "tool_not_allowed"
CODE_UNSAFE_HOST = "unsafe_host"
CODE_PROXY_FORCED_EXTERNAL = "proxy_forced_external"
CODE_INVALID_URL = "invalid_url"
CODE_CLOUD_DENIED = "cloud_denied"

ERROR_CODES = frozenset(
    {
        CODE_OK,
        CODE_OFFLINE,
        CODE_TOOL_NOT_ALLOWED,
        CODE_UNSAFE_HOST,
        CODE_PROXY_FORCED_EXTERNAL,
        CODE_INVALID_URL,
        CODE_CLOUD_DENIED,
    }
)

_MESSAGES: dict[str, str] = {
    CODE_OK: t("network.ok"),
    CODE_OFFLINE: t("network.offline"),
    CODE_TOOL_NOT_ALLOWED: t("network.tool_not_allowed"),
    CODE_UNSAFE_HOST: t("network.unsafe_host", host="_PLACEHOLDER_"),
    CODE_PROXY_FORCED_EXTERNAL: (
        t("network.proxy_forced_external")
    ),
    CODE_INVALID_URL: t("network.invalid_url"),
    CODE_CLOUD_DENIED: t("network.cloud_denied"),
}

_UNKNOWN = "Network policy rejected the request."


def network_message(code: str) -> str:
    """Return a secret-free explanation for a structured network error code."""
    return _MESSAGES.get(code, _UNKNOWN)


class NetworkDeniedError(Exception):
    """Request denied by NetworkPolicy. Messages never echo URLs or secrets."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message if message is not None else network_message(code))


__all__ = [
    "CODE_CLOUD_DENIED",
    "CODE_INVALID_URL",
    "CODE_OFFLINE",
    "CODE_OK",
    "CODE_PROXY_FORCED_EXTERNAL",
    "CODE_TOOL_NOT_ALLOWED",
    "CODE_UNSAFE_HOST",
    "ERROR_CODES",
    "NetworkDeniedError",
    "network_message",
]
