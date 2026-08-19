"""TLS listen tests for Desktop Control (ephemeral self-signed certs)."""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from server.listener import DesktopControlListener
from server.schemas import CODE_UNAUTHORIZED
from server.tls import TlsConfigError, ensure_tls_material, generate_self_signed_cert


def _free_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _make_certs(tmp_path: Path) -> tuple[Path, Path]:
    cert = tmp_path / "test.crt"
    key = tmp_path / "test.key"
    try:
        generate_self_signed_cert(cert, key, common_name="127.0.0.1")
    except TlsConfigError as exc:
        pytest.skip(f"openssl unavailable: {exc}")
    return cert, key


def test_require_tls_without_files_raises() -> None:
    with pytest.raises(TlsConfigError):
        DesktopControlListener(require_tls=True)


def test_tls_listen_rejects_plain_http(tmp_path: Path) -> None:
    cert, key = _make_certs(tmp_path)
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        tls_certfile=cert,
        tls_keyfile=key,
        require_tls=True,
    )
    assert listener.tls_enabled is True
    assert listener.scheme == "https"
    listener.start()
    try:
        plain = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/status",
            method="GET",
        )
        with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
            urllib.request.urlopen(plain, timeout=2)

        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}/v1/status",
            method="GET",
        )
        try:
            urllib.request.urlopen(req, timeout=2, context=ctx)
            raise AssertionError("expected 401 without auth")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            body = json.loads(exc.read().decode("utf-8"))
            assert body["error"]["code"] == CODE_UNAUTHORIZED
    finally:
        listener.stop()


def test_ensure_tls_material_generate(tmp_path: Path) -> None:
    try:
        material = ensure_tls_material(
            cert_dir=tmp_path,
            generate=True,
            common_name="mark-test.local",
        )
    except TlsConfigError as exc:
        pytest.skip(f"openssl unavailable: {exc}")
    assert material.generated is True
    assert material.certfile.is_file()
    assert material.keyfile.is_file()
    again = ensure_tls_material(cert_dir=tmp_path, generate=False)
    assert again.generated is False
