"""SSRF-oriented URL checks. Hosts are inspected as written; no DNS or HTTP."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from mark.safety.errors import UnsafeUrlError

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
    }
)
_BLOCKED_HOST_SUFFIXES = (".metadata.google.internal",)
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
    }
)
_DOTTED_IPV4 = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$")
_HEX_IPV4 = re.compile(r"^0x[0-9a-f]+$")


def check_url(url: str) -> None:
    """Allow only public http(s) hosts. Raise ``UnsafeUrlError`` otherwise.

    Does not resolve DNS or open sockets. Error text never includes the URL.
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrlError()
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError()
    try:
        host = parsed.hostname
    except ValueError:
        raise UnsafeUrlError() from None
    if not host:
        raise UnsafeUrlError()
    if _host_blocked(host.rstrip(".").lower()):
        raise UnsafeUrlError()


def _host_blocked(host: str) -> bool:
    if host in _BLOCKED_HOSTS:
        return True
    if any(host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES):
        return True
    address = _parse_ip(host)
    if address is None:
        return False
    if address in _METADATA_IPS:
        return True
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    )


def _parse_ip(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    dotted = _DOTTED_IPV4.fullmatch(host)
    if dotted is not None and any(len(part) > 1 and part.startswith("0") for part in dotted.groups()):
        # Ambiguous octal-style IPv4 (browsers may treat 0177.0.0.1 as 127.0.0.1).
        return ipaddress.ip_address("127.0.0.1")
    if host.isdigit():
        number = int(host)
        if number < 2**32:
            return ipaddress.IPv4Address(number)
        return None
    if _HEX_IPV4.fullmatch(host):
        number = int(host, 16)
        if number < 2**32:
            return ipaddress.IPv4Address(number)
        return None
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


__all__ = ["check_url"]
