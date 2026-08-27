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
    CODE_OK: "Network policy accepted the request.",
    CODE_OFFLINE: "External network access is disabled in offline mode.",
    CODE_TOOL_NOT_ALLOWED: "This tool is not allowlisted for network access.",
    CODE_UNSAFE_HOST: "Host is not allowed by network policy.",
    CODE_PROXY_FORCED_EXTERNAL: (
        "Proxy settings would send a loopback request through an external proxy."
    ),
    CODE_INVALID_URL: "URL is not a valid http(s) request target.",
    CODE_CLOUD_DENIED: "Cloud providers are not allowed under the current policy.",
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
