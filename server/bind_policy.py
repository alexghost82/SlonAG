"""Desktop Control API bind-host policy.

Default is loopback. Same-LAN private addresses require an explicit
``allow_non_loopback=True`` opt-in. Wildcard and public-internet binds are
denied. Pairing and auth tokens remain mandatory regardless of bind host;
LAN bind is not an anonymous open port.

This module does not open sockets and does not claim public-internet, VPN,
or APNs product capability.
"""

from __future__ import annotations

from mark.network.hosts import is_loopback_host, is_private_lan_host, parse_ip_literal

# Unspecified / wildcard binds are always rejected (even with LAN opt-in).
FORBIDDEN_BIND_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})


class BindHostError(ValueError):
    """Raised when a bind_host violates Desktop Control bind policy."""

    def __init__(self, host: str, message: str | None = None) -> None:
        self.host = host
        super().__init__(
            message
            or (
                "Desktop Control API bind_host must be loopback unless "
                "allow_non_loopback=True is set explicitly for a private "
                "same-LAN address."
            )
        )


def normalize_bind_host(host: str) -> str:
    """Strip brackets / whitespace for classification (preserve original separately)."""
    return str(host).strip().lower().strip("[]")


def is_forbidden_wildcard_bind(host: str) -> bool:
    """True for unspecified IPv4/IPv6 wildcard bind targets."""
    normalized = normalize_bind_host(host)
    if normalized in FORBIDDEN_BIND_HOSTS:
        return True
    address = parse_ip_literal(normalized)
    if address is None:
        return False
    return bool(address.is_unspecified)


def is_same_lan_bind_host(host: str) -> bool:
    """True for RFC1918 / private LAN IP literals (not loopback, not public)."""
    return is_private_lan_host(normalize_bind_host(host))


def validate_bind_host(host: str, *, allow_non_loopback: bool = False) -> str:
    """Validate and return the trimmed bind host string.

    Rules:
    - Empty host → error
    - Default path (``allow_non_loopback=False``): loopback only
    - Opt-in path (``allow_non_loopback=True``): loopback **or** private
      same-LAN IP (RFC1918 / ULA via ``is_private_lan_host``)
    - Wildcards (``0.0.0.0``, ``::``) always denied
    - Public / non-private non-loopback addresses always denied

    Does not resolve DNS hostnames into addresses; non-IP hostnames that are
    not loopback names are rejected.
    """
    trimmed = str(host).strip()
    if not trimmed:
        raise BindHostError(trimmed, "bind_host must be a non-empty string.")

    if is_forbidden_wildcard_bind(trimmed):
        raise BindHostError(
            trimmed,
            "Wildcard bind hosts (0.0.0.0 / ::) are not allowed. "
            "Bind to 127.0.0.1 by default, or to a specific private LAN "
            "address with allow_non_loopback=True.",
        )

    normalized = normalize_bind_host(trimmed)
    if is_loopback_host(normalized):
        return trimmed

    if not allow_non_loopback:
        raise BindHostError(trimmed)

    if is_same_lan_bind_host(trimmed):
        return trimmed

    raise BindHostError(
        trimmed,
        "Non-loopback bind_host must be a private same-LAN address "
        "(RFC1918 / ULA) when allow_non_loopback=True. "
        "Public-internet binds are not supported.",
    )


__all__ = [
    "FORBIDDEN_BIND_HOSTS",
    "BindHostError",
    "is_forbidden_wildcard_bind",
    "is_same_lan_bind_host",
    "normalize_bind_host",
    "validate_bind_host",
]
