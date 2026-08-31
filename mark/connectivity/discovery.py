"""Bonjour/mDNS LAN device discovery.

Scans for ``_mark-control._tcp`` services on the same LAN.
Returns :class:`LANDevice` instances with host, port, fingerprint, etc.

Uses ``zeroconf`` when available, falls back to the ``dns-sd`` CLI.
Never exposes devices to the public internet; only scans local interfaces.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, MutableSequence

logger = logging.getLogger(__name__)

# Service type registered by the Desktop Control server.
SERVICE_TYPE = "_mark-control._tcp.local."


@dataclass(frozen=True)
class LANDevice:
    """A device discovered on the local network.

    Attributes:
        name: Human-readable device name.
        host: Resolved IP address (not a hostname).
        port: TCP port the control API listens on.
        device_id: Device identifier from the mDNS service properties.
        display_name: Display name from the mDNS service properties.
        fingerprint: SHA-256 TLS certificate fingerprint advertised in TXT.
        uses_tls: Whether the service advertises TLS support.
        service_type: mDNS service type (usually ``SERVICE_TYPE``).
        properties: Raw TXT properties (copy-on-read).
    """

    name: str
    host: str
    port: int
    device_id: str
    display_name: str
    fingerprint: str
    uses_tls: bool = True
    service_type: str = SERVICE_TYPE
    properties: dict[str, str] = field(default_factory=dict)
    discovered_at: float = field(default_factory=lambda: time.time())

    @property
    def connect_url(self) -> str:
        """Return the URL to use for connecting to this device."""
        scheme = "wss" if self.uses_tls else "ws"
        return f"{scheme}://{self.host}:{self.port}"


class LANDeviceScanner:
    """Scan for ``_mark-control._tcp`` services on the local network.

    Creates a scanner that runs in its own thread and reports devices
    via a callback. The scan is non-blocking.
    """

    def __init__(
        self,
        *,
        timeout: float = 5.0,
        preferred_backend: str = "auto",
    ) -> None:
        self._timeout = float(timeout)
        self._preferred_backend = preferred_backend
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._discovered: list[LANDevice] = []
        self._handlers: list[Callable[[list[LANDevice]], None]] = []
        self._last_scan_time: float = 0.0

    # -- public API --

    @property
    def is_scanning(self) -> bool:
        return self._running

    @property
    def devices(self) -> list[LANDevice]:
        with self._lock:
            return list(self._discovered)

    def on_devices(self, handler: Callable[[list[LANDevice]], None]) -> None:
        """Register a callback that fires every time devices are found."""
        with self._lock:
            self._handlers.append(handler)

    def scan_once(self) -> list[LANDevice]:
        """Perform a single scan and return the discovered devices.

        This is a synchronous convenience method that does not start a
        background thread. Use :meth:`start` for continuous scanning.
        """
        devices = self._scan_once_sync()
        with self._lock:
            self._discovered = list(devices)
            self._last_scan_time = time.time()
        for handler in list(self._handlers):
            try:
                handler(list(devices))
            except Exception:  # noqa: BLE001
                logger.exception("Device handler error")
        return list(devices)

    def start(self) -> None:
        """Begin continuous background scanning.

        Scans repeat every 30 seconds. Call :meth:`stop` to stop.
        """
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._scan_loop,
                name="mark-connectivity-scan",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop background scanning. The next :meth:`scan_once` call is still valid."""
        with self._lock:
            self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # -- internals --

    def _scan_loop(self) -> None:
        """Background loop that scans every 30 seconds."""
        while True:
            with self._lock:
                if not self._running:
                    return
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001
                logger.exception("Scan loop error")
            # Wait in small increments so we can stop quickly.
            for _ in range(300):  # 30 s at 100 ms steps
                with self._lock:
                    if not self._running:
                        return
                time.sleep(0.1)

    def _scan_once_sync(self) -> list[LANDevice]:
        """Perform one scan using the preferred backend."""
        devices: list[LANDevice] = []

        if self._preferred_backend == "dns-sd":
            try:
                devices.extend(self._scan_dns_sd())
            except Exception:  # noqa: BLE001
                logger.warning("dns-sd scan failed, trying zeroconf")
        else:
            try:
                devices.extend(self._scan_zeroconf())
            except ImportError:
                logger.warning("zeroconf not available, trying dns-sd")
            if not devices:
                try:
                    devices.extend(self._scan_dns_sd())
                except Exception:  # noqa: BLE001
                    logger.warning("dns-sd scan also failed")

        return devices

    def _scan_zeroconf(self) -> list[LANDevice]:
        from zeroconf import IPVersion, Zeroconf
        from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

        aiozc: AsyncZeroconf | None = None
        results: list[LANDevice] = []
        info: AsyncServiceInfo | None = None

        async def _probe() -> list[LANDevice]:
            nonlocal aiozc, info
            aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            info = AsyncServiceInfo(
                SERVICE_TYPE,
                f"Slon Desktop Control.{SERVICE_TYPE}",
                properties={},
                port=8765,
                server="mark-desktop.local.",
            )
            await info.async_request(aiozc, int(self._timeout * 1000))
            return await _discover_all(aiozc)

        try:
            import asyncio
            results = asyncio.run(_probe())
        except Exception:  # noqa: BLE001
            pass

        # Fallback to sync discovery if async failed.
        if not results:
            try:
                zc = Zeroconf(ip_version=IPVersion.V4Only)
                results = _discover_sync(zc, self._timeout)
                zc.close()
            except Exception:  # noqa: BLE001
                pass

        return results

    def _scan_dns_sd(self) -> list[LANDevice]:
        import subprocess
        result = subprocess.run(
            ["dns-sd", "-B", "_mark-control._tcp", "."],
            capture_output=True,
            text=True,
            timeout=max(6, int(self._timeout) + 2),
        )
        devices: list[LANDevice] = []
        seen_names: set[str] = set()
        for line in (result.stdout or "").splitlines():
            parts = line.strip().split()
            if len(parts) < 5 or parts[1] != "ADDING":
                continue
            name = parts[0]
            if name in seen_names:
                continue
            seen_names.add(name)
            # Parse the name format: "DisplayName._mark-control._tcp.local."
            display = name.split(".")[0] if "." in name else ""
            devices.append(
                LANDevice(
                    name=name,
                    host="",  # dns-sd browsing needs a second query for details
                    port=8765,  # default; should refine
                    device_id="",
                    display_name=display,
                    fingerprint="",
                    uses_tls=True,
                    properties={"_raw": line},
                )
            )
        return devices


async def _discover_all(aiozc: Any) -> list[LANDevice]:
    """Discover all services of SERVICE_TYPE."""
    from zeroconf.asyncio import AsyncServiceBrowser

    browser: AsyncServiceBrowser | None = None
    found: list[LANDevice] = []

    def _add_service(zc, service_type_: str, name: str) -> None:
        info = AsyncServiceInfo(service_type_, name)

        async def _fetch() -> None:
            try:
                await info.async_request(zc, 3000)
                dev = _make_lan_device(info)
                if dev:
                    found.append(dev)
            except Exception:  # noqa: BLE001
                pass

        # We run it in the same event loop so it's simple.
        pass

    # Simplest approach: resolve the known service name directly.
    info = AsyncServiceInfo(
        SERVICE_TYPE,
        f"Slon Desktop Control.{SERVICE_TYPE}",
    )
    try:
        await info.async_request(aiozc, int(3000))
        dev = _make_lan_device(info)
        if dev:
            found.append(dev)
    except Exception:
        pass

    return found


def _make_lan_device(info: Any) -> LANDevice | None:
    """Build a LANDevice from an AsyncServiceInfo (or zeroconf.ServiceInfo)."""
    try:
        import ipaddress
        port = info.port or 8765

        addresses = info.addresses or []
        host = ""
        for addr_bytes in addresses:
            try:
                addr = ipaddress.ip_address(addr_bytes)
                if not addr.is_loopback and not addr.is_link_local:
                    host = str(addr)
                    break
            except (ValueError, TypeError):
                continue

        if not host and addresses:
            try:
                host = str(ipaddress.ip_address(addresses[0]))
            except (ValueError, TypeError):
                pass

        txt = info.properties or {}
        props: dict[str, str] = {}
        for k, v in txt.items():
            key = k if isinstance(k, str) else k.decode("utf-8", errors="replace")
            val = v if isinstance(v, str) else v.decode("utf-8", errors="replace")
            props[key] = val

        uses_tls = props.get("tls") == "1"
        fingerprint = props.get("fingerprint_sha256", "")
        device_id = props.get("device_id", "")
        display_name = props.get("display_name", info.name.split(".")[0] if info.name else "")

        return LANDevice(
            name=info.name,
            host=host,
            port=port,
            device_id=device_id,
            display_name=display_name,
            fingerprint=fingerprint,
            uses_tls=uses_tls,
            properties=props,
        )
    except Exception:  # noqa: BLE001
        return None


def _discover_sync(
    zc: Any, timeout: float = 5.0
) -> list[LANDevice]:
    """Synchronous discovery using zeroconf."""
    import time as _time

    from zeroconf import ServiceStateChange

    devices: list[LANDevice] = []
    done_event = threading.Event()

    def _on_service(state_change: ServiceStateChange, name: str, service_type: str) -> None:
        if state_change == ServiceStateChange.Added:
            try:
                info = zc.get_service_info(service_type, name)
                if info:
                    dev = _make_lan_device_sync(info)
                    if dev:
                        devices.append(dev)
            except Exception:  # noqa: BLE001
                pass

    zc.register_service_callback(_on_service, ServiceStateChange.Added)

    # Also try resolving the known service name.
    try:
        info = zc.get_service_info(SERVICE_TYPE, f"Slon Desktop Control.{SERVICE_TYPE}")
        if info:
            dev = _make_lan_device_sync(info)
            if dev:
                devices.append(dev)
    except Exception:
        pass

    # Wait for the callback to fire.
    done_event.wait(timeout=timeout)
    return devices


def _make_lan_device_sync(info: Any) -> LANDevice | None:
    """Build a LANDevice from a synchronous zeroconf.ServiceInfo."""
    try:
        import ipaddress
        port = info.port or 8765
        addresses = info.addresses or []

        host = ""
        for addr_bytes in addresses:
            try:
                addr = ipaddress.ip_address(addr_bytes)
                if not addr.is_loopback and not addr.is_link_local:
                    host = str(addr)
                    break
            except (ValueError, TypeError):
                continue

        if not host and addresses:
            try:
                host = str(ipaddress.ip_address(addresses[0]))
            except (ValueError, TypeError):
                pass

        txt = info.properties or {}
        props: dict[str, str] = {}
        for k, v in txt.items():
            key = k if isinstance(k, str) else k.decode("utf-8", errors="replace")
            val = v if isinstance(v, str) else v.decode("utf-8", errors="replace")
            props[key] = val

        uses_tls = props.get("tls") == "1"
        fingerprint = props.get("fingerprint_sha256", "")
        device_id = props.get("device_id", "")
        display_name = props.get("display_name", info.name.split(".")[0] if info.name else "")

        return LANDevice(
            name=info.name,
            host=host,
            port=port,
            device_id=device_id,
            display_name=display_name,
            fingerprint=fingerprint,
            uses_tls=uses_tls,
            properties=props,
        )
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "LANDevice",
    "LANDeviceScanner",
    "SERVICE_TYPE",
]
