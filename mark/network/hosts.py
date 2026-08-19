"""Host classification for NetworkPolicy. No DNS and no sockets."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})
_METADATA_HOSTS = frozenset(
    {
        "metadata",
        "metadata.google.internal",
    }
)
_METADATA_HOST_SUFFIXES = (".metadata.google.internal",)
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
    }
)
_DOTTED_IPV4 = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)$")
_HEX_IPV4 = re.compile(r"^0x[0-9a-f]+$", re.IGNORECASE)
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def parse_request_url(url: str) -> tuple[str, str] | None:
    """Return ``(scheme, host)`` for a valid http(s) URL, else ``None``.

    Does not resolve DNS. Error paths never need the original URL echoed.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    try:
        host = parsed.hostname
    except ValueError:
        return None
    if not host:
        return None
    return parsed.scheme.lower(), host.rstrip(".").lower()


def domain_of(url: str) -> str:
    """Return a redaction-safe hostname, or empty when the URL is unusable."""
    parsed = parse_request_url(url)
    if parsed is None:
        return ""
    return parsed[1]


def is_loopback_host(host: str) -> bool:
    """Return True for localhost names or loopback IP literals."""
    normalized = host.rstrip(".").lower()
    if normalized in _LOOPBACK_NAMES:
        return True
    address = parse_ip_literal(normalized)
    if address is None:
        return False
    return bool(address.is_loopback)


def is_metadata_or_link_local_host(host: str) -> bool:
    """Return True for cloud-metadata hostnames and unambiguous SSRF literals."""
    normalized = host.rstrip(".").lower()
    if normalized in _METADATA_HOSTS:
        return True
    if any(normalized.endswith(suffix) for suffix in _METADATA_HOST_SUFFIXES):
        return True
    address = parse_ip_literal(normalized)
    if address is None:
        return False
    if address in _METADATA_IPS:
        return True
    return bool(
        address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    )


def is_private_lan_host(host: str) -> bool:
    """Return True for private RFC1918 / ULA addresses that are not loopback."""
    address = parse_ip_literal(host.rstrip(".").lower())
    if address is None:
        return False
    if address.is_loopback:
        return False
    return bool(address.is_private)


def parse_ip_literal(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an IP literal, including ambiguous decimal/hex/octal IPv4 forms."""
    dotted = _DOTTED_IPV4.fullmatch(host)
    if dotted is not None and any(
        len(part) > 1 and part.startswith("0") for part in dotted.groups()
    ):
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
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            host
        )
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def proxy_would_force_external(environ: dict[str, str], target_host: str) -> bool:
    """True when a non-loopback proxy would intercept a loopback target."""
    if not is_loopback_host(target_host):
        return False
    for key in _PROXY_ENV_KEYS:
        raw = environ.get(key)
        if not raw or not str(raw).strip():
            continue
        proxy_host = _proxy_host(str(raw).strip())
        if proxy_host is None:
            # Unparseable proxy value is treated as unsafe for loopback.
            return True
        if not is_loopback_host(proxy_host):
            return True
    return False


def _proxy_host(proxy_value: str) -> str | None:
    value = proxy_value.strip()
    if "://" not in value:
        value = "http://" + value
    try:
        parsed = urlparse(value)
        host = parsed.hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.rstrip(".").lower()


__all__ = [
    "domain_of",
    "is_loopback_host",
    "is_metadata_or_link_local_host",
    "is_private_lan_host",
    "parse_ip_literal",
    "parse_request_url",
    "proxy_would_force_external",
]
