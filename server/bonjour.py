"""LAN Bonjour/mDNS advertisement for Desktop Control API.

Uses ``zeroconf`` when installed; otherwise falls back to macOS ``dns-sd``
subprocess. Never binds wildcards; advertises the already-validated bind host.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Mapping

SERVICE_TYPE = "_mark-control._tcp.local."
SERVICE_NAME = "Slon Desktop Control"


@dataclass
class BonjourAdvertisement:
    """Handle for a running advertisement (stop to unregister)."""

    backend: str
    host: str
    port: int
    _stop: Any

    def stop(self) -> None:
        stop = self._stop
        if callable(stop):
            stop()


class BonjourError(RuntimeError):
    """Advertisement could not start."""


def _advertise_zeroconf(
    host: str,
    port: int,
    *,
    name: str,
    properties: Mapping[str, str] | None = None,
) -> BonjourAdvertisement:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf

    zc = Zeroconf(ip_version=IPVersion.V4Only)
    txt = {"path": b"/v1", "host": host.encode("utf-8")}
    txt.update({key: value.encode("utf-8") for key, value in (properties or {}).items()})
    info = ServiceInfo(
        SERVICE_TYPE,
        f"{name}.{SERVICE_TYPE}",
        port=port,
        addresses=[],  # let zeroconf fill from interfaces; properties carry host
        properties=txt,
        server="mark-desktop.local.",
    )
    # Prefer explicit host when it is a concrete IPv4.
    try:
        parts = [int(p) for p in host.split(".")]
        if len(parts) == 4 and all(0 <= p <= 255 for p in parts):
            info = ServiceInfo(
                SERVICE_TYPE,
                f"{name}.{SERVICE_TYPE}",
                addresses=[bytes(parts)],
                port=port,
                properties=txt,
                server="mark-desktop.local.",
            )
    except ValueError:
        pass
    zc.register_service(info)

    def _stop() -> None:
        try:
            zc.unregister_service(info)
        finally:
            zc.close()

    return BonjourAdvertisement(backend="zeroconf", host=host, port=port, _stop=_stop)


def _advertise_dns_sd(
    host: str,
    port: int,
    *,
    name: str,
    properties: Mapping[str, str] | None = None,
) -> BonjourAdvertisement:
    dns_sd = shutil.which("dns-sd")
    if not dns_sd:
        raise BonjourError("dns-sd not found (macOS Bonjour tools)")
    # dns-sd -R name type domain port
    arguments = [
            dns_sd,
            "-R",
            name,
            "_mark-control._tcp",
            ".",
            str(port),
            "path=/v1",
            f"host={host}",
        ]
    arguments.extend(f"{key}={value}" for key, value in (properties or {}).items())
    proc = subprocess.Popen(  # noqa: S603 — fixed binary from PATH
        arguments,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _stop() -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    return BonjourAdvertisement(backend="dns-sd", host=host, port=port, _stop=_stop)


def start_bonjour(
    host: str,
    port: int,
    *,
    name: str = SERVICE_NAME,
    prefer: str = "auto",
    properties: Mapping[str, str] | None = None,
) -> BonjourAdvertisement:
    """Register ``_mark-control._tcp`` for ``host:port``.

    ``prefer``: ``auto`` | ``zeroconf`` | ``dns-sd``.
    """
    if port <= 0 or port > 65535:
        raise BonjourError("invalid port")
    errors: list[str] = []
    order: list[str]
    if prefer == "zeroconf":
        order = ["zeroconf"]
    elif prefer == "dns-sd":
        order = ["dns-sd"]
    else:
        order = ["zeroconf", "dns-sd"]

    for backend in order:
        try:
            if backend == "zeroconf":
                return _advertise_zeroconf(
                    host,
                    port,
                    name=name,
                    properties=properties,
                )
            return _advertise_dns_sd(
                host,
                port,
                name=name,
                properties=properties,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{backend}: {exc}")
    raise BonjourError("; ".join(errors) or "no Bonjour backend")


class BonjourManager:
    """Thread-safe start/stop wrapper for the Desktop listener."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._adv: BonjourAdvertisement | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._adv is not None

    def start(self, host: str, port: int, **kwargs: Any) -> BonjourAdvertisement:
        with self._lock:
            if self._adv is not None:
                self._adv.stop()
                self._adv = None
            adv = start_bonjour(host, port, **kwargs)
            self._adv = adv
            return adv

    def stop(self) -> None:
        with self._lock:
            if self._adv is not None:
                self._adv.stop()
                self._adv = None


__all__ = [
    "SERVICE_NAME",
    "SERVICE_TYPE",
    "BonjourAdvertisement",
    "BonjourError",
    "BonjourManager",
    "start_bonjour",
]
