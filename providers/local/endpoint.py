"""Loopback URL policy for local adapters.

Remote hosts are rejected when ``allow_remote`` is false, before any HTTP.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from providers.errors import ProviderError, ProviderOfflineError

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_LOCALHOST_NAMES = frozenset({"localhost"})


def parse_endpoint_host(base_url: str) -> str:
    """Return the lowercase hostname from an http(s) URL."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ProviderError("base_url must be a non-empty URL")
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ProviderError("base_url must be an http or https URL")
    host = parsed.hostname
    if not host:
        raise ProviderError("base_url must include a host")
    return host.rstrip(".").lower()


def is_loopback_host(host: str) -> bool:
    """Return True for localhost or a loopback IP (not LAN or public DNS)."""
    if host in _LOCALHOST_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_loopback_url(base_url: str) -> bool:
    """Return True when ``base_url`` points at a loopback host."""
    try:
        return is_loopback_host(parse_endpoint_host(base_url))
    except ProviderError:
        return False


def origin_of(base_url: str) -> str:
    """Return ``scheme://netloc`` so /v1 vs bare host defaults share paths."""
    parsed = urlparse(base_url.strip())
    return f"{parsed.scheme}://{parsed.netloc}"


def join_endpoint(base_url: str, path: str) -> str:
    """Join ``base_url`` origin with an absolute API path."""
    return origin_of(base_url).rstrip("/") + "/" + path.lstrip("/")


def assert_endpoint_allowed(
    base_url: str,
    *,
    allow_remote: bool,
    provider_id: str,
) -> None:
    """Raise ``ProviderOfflineError`` for a non-loopback host when denied."""
    host = parse_endpoint_host(base_url)
    if allow_remote or is_loopback_host(host):
        return
    raise ProviderOfflineError(
        f"refusing non-loopback host {host!r} while allow_remote is false",
        provider_id=provider_id,
    )
