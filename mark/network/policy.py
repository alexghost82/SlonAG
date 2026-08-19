"""Headless NetworkPolicy — single gate for future HTTP/DNS clients."""

from __future__ import annotations

import os
from collections.abc import Mapping

from mark.network.errors import (
    CODE_INVALID_URL,
    CODE_OFFLINE,
    CODE_OK,
    CODE_PROXY_FORCED_EXTERNAL,
    CODE_TOOL_NOT_ALLOWED,
    CODE_UNSAFE_HOST,
    NetworkDeniedError,
)
from mark.network.hosts import (
    domain_of,
    is_loopback_host,
    is_metadata_or_link_local_host,
    is_private_lan_host,
    parse_request_url,
    proxy_would_force_external,
)
from mark.network.journal import NetworkJournal
from mark.network.types import (
    CLOUD_PROVIDER_IDS,
    PRIVACY_FULLY_LOCAL,
    NetworkDecision,
    NetworkJournalEntry,
    NetworkMode,
)


def _coerce_mode(mode: NetworkMode | str) -> NetworkMode:
    if isinstance(mode, NetworkMode):
        return mode
    return NetworkMode(str(mode))


class NetworkPolicy:
    """Decide whether a client may leave the host for a given URL/tool.

    Does not perform DNS lookups or open sockets. Does not mutate
    ``os.environ``; pass ``environ=`` in tests to inject proxy settings.
    """

    def __init__(
        self,
        mode: NetworkMode | str = NetworkMode.HYBRID,
        *,
        tool_allowlist: frozenset[str] | None = None,
        allow_private_lan: bool = False,
        privacy_profile: str | None = None,
        environ: Mapping[str, str] | None = None,
        journal: NetworkJournal | None = None,
    ) -> None:
        self.mode = _coerce_mode(mode)
        self.tool_allowlist: frozenset[str] = (
            frozenset() if tool_allowlist is None else frozenset(tool_allowlist)
        )
        self.allow_private_lan = bool(allow_private_lan)
        self.privacy_profile = privacy_profile
        self._environ: Mapping[str, str] | None = environ
        self._journal = journal if journal is not None else NetworkJournal()

    def check_request(
        self,
        *,
        url: str,
        tool: str | None = None,
        purpose: str = "",
    ) -> NetworkDecision:
        """Allow or deny an http(s) request target without contacting the network."""
        parsed = parse_request_url(url)
        if parsed is None:
            return self._decide(
                allowed=False,
                reason=CODE_INVALID_URL,
                domain="",
                tool=tool,
                purpose=purpose,
            )

        _scheme, host = parsed
        domain = host

        if proxy_would_force_external(self._proxy_environ(), host):
            return self._decide(
                allowed=False,
                reason=CODE_PROXY_FORCED_EXTERNAL,
                domain=domain,
                tool=tool,
                purpose=purpose,
            )

        if is_loopback_host(host):
            return self._decide(
                allowed=True,
                reason=CODE_OK,
                domain=domain,
                tool=tool,
                purpose=purpose,
            )

        if is_metadata_or_link_local_host(host):
            return self._decide(
                allowed=False,
                reason=CODE_UNSAFE_HOST,
                domain=domain,
                tool=tool,
                purpose=purpose,
            )

        if is_private_lan_host(host) and not self.allow_private_lan:
            return self._decide(
                allowed=False,
                reason=CODE_UNSAFE_HOST,
                domain=domain,
                tool=tool,
                purpose=purpose,
            )

        if self.mode is NetworkMode.OFFLINE:
            return self._decide(
                allowed=False,
                reason=CODE_OFFLINE,
                domain=domain,
                tool=tool,
                purpose=purpose,
            )

        if self.mode is NetworkMode.TOOLS_ONLY:
            if tool is None or tool not in self.tool_allowlist:
                return self._decide(
                    allowed=False,
                    reason=CODE_TOOL_NOT_ALLOWED,
                    domain=domain,
                    tool=tool,
                    purpose=purpose,
                )
            return self._decide(
                allowed=True,
                reason=CODE_OK,
                domain=domain,
                tool=tool,
                purpose=purpose,
            )

        # HYBRID: public http(s) allowed; private LAN only with allow_private_lan.
        return self._decide(
            allowed=True,
            reason=CODE_OK,
            domain=domain,
            tool=tool,
            purpose=purpose,
        )

    def require_request(
        self,
        *,
        url: str,
        tool: str | None = None,
        purpose: str = "",
    ) -> NetworkDecision:
        """Like ``check_request``, but raise ``NetworkDeniedError`` on deny."""
        decision = self.check_request(url=url, tool=tool, purpose=purpose)
        if not decision.allowed:
            raise NetworkDeniedError(decision.reason)
        return decision

    def allows_cloud_provider(self, provider_id: str) -> bool:
        """Return True only for cloud ids permitted by mode / privacy profile."""
        if provider_id not in CLOUD_PROVIDER_IDS:
            return False
        if self.mode is NetworkMode.OFFLINE:
            return False
        if self.privacy_profile == PRIVACY_FULLY_LOCAL:
            return False
        return True

    def activity(self) -> list[NetworkJournalEntry]:
        """Snapshot of journaled decisions for a future UI."""
        return self._journal.activity()

    def recent(self, limit: int = 50) -> list[NetworkJournalEntry]:
        """Newest journal entries (oldest-first within the window)."""
        return self._journal.recent(limit)

    def _proxy_environ(self) -> dict[str, str]:
        if self._environ is not None:
            return {str(k): str(v) for k, v in self._environ.items()}
        # Copy only proxy-related keys; never mutate os.environ.
        keys = (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
        return {key: value for key in keys if (value := os.environ.get(key))}

    def _decide(
        self,
        *,
        allowed: bool,
        reason: str,
        domain: str,
        tool: str | None,
        purpose: str,
    ) -> NetworkDecision:
        self._journal.record(
            tool=tool,
            domain=domain or domain_of(""),
            reason=reason,
            allowed=allowed,
        )
        return NetworkDecision(
            allowed=allowed,
            reason=reason,
            domain=domain,
            tool=tool,
            purpose=purpose,
        )


__all__ = [
    "NetworkPolicy",
]
