"""TLS listen tests for Desktop Control (ephemeral self-signed certs)."""

from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from gateway.service import SlonGateway
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
    assert material.keyfile.stat().st_mode & 0o777 == 0o600
    decoded = ssl._ssl._test_decode_cert(str(material.certfile))
    assert ("DNS", "mark-test.local") in decoded["subjectAltName"]
    again = ensure_tls_material(cert_dir=tmp_path, generate=False)
    assert again.generated is False


def test_tls_gateway_rejects_unauthorized_websocket_upgrade(tmp_path: Path) -> None:
    material = ensure_tls_material(
        cert_dir=tmp_path / "certs", generate=True, common_name="127.0.0.1"
    )
    gateway = SlonGateway(
        database_path=tmp_path / "gateway.sqlite3",
        artifact_root=tmp_path / "artifacts", signing_key=b"gateway-tls-test-key",
    )
    listener = DesktopControlListener(
        bind_port=_free_loopback_port(), tls_certfile=material.certfile,
        tls_keyfile=material.keyfile, require_tls=True, gateway=gateway,
    )
    host, port = listener.start()
    try:
        request = urllib.request.Request(
            f"https://{host}:{port}/v1/gateway/ws",
            headers={"Upgrade": "websocket", "Sec-WebSocket-Key": "dGVzdA=="},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                request, timeout=2, context=ssl._create_unverified_context()
            )
        assert caught.value.code == 401
    finally:
        listener.stop()
        gateway.close()
