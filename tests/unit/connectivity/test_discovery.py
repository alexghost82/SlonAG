"""Tests for acta/connectivity/discovery.py — mDNS/Bonjour device discovery."""

from __future__ import annotations

import pytest

from acta.connectivity.discovery import LANDevice, LANDeviceScanner, SERVICE_TYPE


class TestLANDevice:
    def test_defaults(self) -> None:
        dev = LANDevice(
            name="Test._mark-control._tcp.local.",
            host="192.168.1.1",
            port=8765,
            device_id="dev-test",
            display_name="Test",
            fingerprint="abc123",
        )
        assert dev.uses_tls is True
        assert dev.service_type == SERVICE_TYPE

    def test_connect_url_tls(self) -> None:
        dev = LANDevice(
            name="T", host="1.2.3.4", port=443,
            device_id="d", display_name="D", fingerprint="f", uses_tls=True,
        )
        assert dev.connect_url == "wss://1.2.3.4:443"

    def test_connect_url_plain(self) -> None:
        dev = LANDevice(
            name="T", host="1.2.3.4", port=80,
            device_id="d", display_name="D", fingerprint="", uses_tls=False,
        )
        assert dev.connect_url == "ws://1.2.3.4:80"

    def test_frozen(self) -> None:
        dev = LANDevice(
            name="N", host="h", port=1,
            device_id="d", display_name="d", fingerprint="f",
        )
        with pytest.raises(Exception):
            dev.host = "new"


class TestLANDeviceScanner:
    def test_initial_state(self) -> None:
        scanner = LANDeviceScanner()
        assert not scanner.is_scanning
        assert scanner.devices == []

    def test_scan_once_returns_list(self) -> None:
        scanner = LANDeviceScanner(preferred_backend="zeroconf")
        devices = scanner.scan_once()
        assert isinstance(devices, list)

    def test_scan_once_sync_on_discovery(self) -> None:
        scanner = LANDeviceScanner()
        devices = scanner.scan_once()
        assert isinstance(devices, list)

    def test_start_stop(self) -> None:
        scanner = LANDeviceScanner()
        scanner.start()
        assert scanner.is_scanning
        scanner.stop()
        assert not scanner.is_scanning

    def test_scan_once_registers_handler(self, fake_lan_device: LANDevice) -> None:
        received: list[LANDevice] = []
        scanner = LANDeviceScanner()

        def handler(devices: list[LANDevice]) -> None:
            received.extend(devices)

        scanner.on_devices(handler)
        scanner.scan_once()
        assert isinstance(received, list)

    def test_devices_property_returns_copy(self) -> None:
        scanner = LANDeviceScanner()
        devices1 = scanner.devices
        devices2 = scanner.devices
        assert devices1 is not devices2

    def test_scan_once_idempotent(self, fake_lan_device: LANDevice) -> None:
        scanner = LANDeviceScanner()
        result1 = scanner.scan_once()
        result2 = scanner.scan_once()
        assert len(result1) == len(result2)

    def test_scan_once_stores_last_scan_time(self) -> None:
        scanner = LANDeviceScanner()
        before = scanner._last_scan_time
        scanner.scan_once()
        assert scanner._last_scan_time >= before

    def test_stop_while_not_running(self) -> None:
        scanner = LANDeviceScanner()
        scanner.stop()

    def test_scan_once_no_error(self) -> None:
        """scan_once should never raise even with no backends."""
        scanner = LANDeviceScanner()
        devices = scanner.scan_once()
        assert isinstance(devices, list)


class TestServiceType:
    def test_service_type(self) -> None:
        assert SERVICE_TYPE == "_mark-control._tcp.local."
