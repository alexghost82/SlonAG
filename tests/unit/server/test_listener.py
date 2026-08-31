"""Live Desktop Control listener: bind policy + start/stop (loopback only)."""

from __future__ import annotations

import base64
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from acta.bridge.control_plane import DesktopControlPlane
from server.bind_policy import BindHostError
from server.listener import DesktopControlListener
from server.schemas import CODE_UNAUTHORIZED
from server.tls import TlsConfigError


def _free_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _rows(body: dict[str, object], key: str) -> list[dict[str, object]]:
    raw = body.get(key)
    assert isinstance(raw, list)
    assert all(isinstance(item, dict) for item in raw)
    return [dict(item) for item in raw if isinstance(item, dict)]


def test_listener_rejects_wildcard_and_public() -> None:
    with pytest.raises(BindHostError):
        DesktopControlListener(bind_host="0.0.0.0")
    with pytest.raises(BindHostError):
        DesktopControlListener(bind_host="8.8.8.8", allow_non_loopback=True)


def test_listener_default_not_listening_until_start() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(bind_host="127.0.0.1", bind_port=port)
    assert listener.listening is False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_listener_start_stop_loopback_http() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(bind_host="127.0.0.1", bind_port=port)
    host, bound_port = listener.start()
    assert listener.listening is True
    assert bound_port == port
    assert host == "127.0.0.1"
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/status",
            method="GET",
        )
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("expected 401 without auth")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            body = json.loads(exc.read().decode("utf-8"))
            assert body["error"]["code"] == CODE_UNAUTHORIZED
    finally:
        listener.stop()
    assert listener.listening is False


def test_listener_pairing_and_token_auth_roundtrip() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        signing_key=b"unit-test-signing-key-32bytes!!",
    )
    listener.start()
    try:
        start = listener.handle(
            "POST",
            "/v1/pairing/start",
            body={"idempotency_key": "p-start-1"},
        )
        assert start.status_code == 200
        code = start.body["code"]
        assert isinstance(code, str) and len(code) == 6

        complete = listener.handle(
            "POST",
            "/v1/pairing/complete",
            body={
                "code": code,
                "device_name": "iphone-test",
                "idempotency_key": "p-complete-1",
            },
        )
        assert complete.status_code == 200
        device_id = complete.body["device_id"]
        device_secret = complete.body["device_secret"]
        assert isinstance(device_id, str) and device_id
        assert isinstance(device_secret, str) and device_secret

        token = listener.handle(
            "POST",
            "/v1/auth/token",
            body={"device_id": device_id, "device_secret": device_secret},
        )
        assert token.status_code == 200
        access = token.body["access_token"]
        assert isinstance(access, str) and access

        status = listener.handle(
            "GET",
            "/v1/status",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert status.status_code == 200
        assert status.body.get("online") is True
        assert "api_key" not in status.body
        revoked = listener.handle(
            "POST",
            "/v1/pairing/revoke",
            headers={"Authorization": f"Bearer {access}"},
            body={"idempotency_key": "revoke-self-1"},
        )
        assert revoked.body == {"revoked": True}
        denied = listener.handle(
            "GET",
            "/v1/status",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert denied.status_code == 401
    finally:
        listener.stop()


def test_listener_lan_requires_tls_material() -> None:
    with pytest.raises(TlsConfigError, match="LAN control requires TLS"):
        DesktopControlListener(
            bind_host="192.168.1.50",
            allow_non_loopback=True,
            bind_port=18765,
        )


def test_listener_control_plane_status_chat_and_runtime() -> None:
    seen: list[str] = []
    plane = DesktopControlPlane(provider_id="gemini", model_id="live")

    def reply(text: str) -> None:
        seen.append(text)
        plane.append_log("Jarvis: systems nominal")

    plane.bind_text_handler(reply)
    plane.bind_command("pause", lambda: plane.update_state(assistant_state="MUTED"))
    listener = DesktopControlListener(
        signing_key=b"unit-test-signing-key-32bytes!!",
        control_plane=plane,
    )

    start = listener.handle(
        "POST",
        "/v1/pairing/start",
        body={"idempotency_key": "control-start"},
    )
    complete = listener.handle(
        "POST",
        "/v1/pairing/complete",
        body={
            "code": start.body["code"],
            "device_name": "iphone-control",
            "idempotency_key": "control-complete",
        },
    )
    token = listener.handle(
        "POST",
        "/v1/auth/token",
        body={
            "device_id": complete.body["device_id"],
            "device_secret": complete.body["device_secret"],
        },
    )
    headers = {"Authorization": f"Bearer {token.body['access_token']}"}

    status = listener.handle("GET", "/v1/status", headers=headers)
    assert status.status_code == 200
    assert status.body["provider_id"] == "gemini"
    assert status.body["model_id"] == "live"
    assert "system_metrics" in status.body

    chat = listener.handle(
        "POST",
        "/v1/chat",
        headers=headers,
        body={
            "message": "status report",
            "conversation_id": "c1",
            "idempotency_key": "chat-live-1",
        },
    )
    assert chat.status_code == 200
    assert chat.body["delta"] == "systems nominal"
    assert seen == ["status report"]

    control = listener.handle(
        "POST",
        "/v1/runtime/control",
        headers=headers,
        body={"action": "pause", "idempotency_key": "runtime-pause-1"},
    )
    assert control.status_code == 200
    assert control.body == {"accepted": True, "state": "MUTED"}


def test_listener_live_models_memory_files_and_task_approval(tmp_path: Path) -> None:
    @dataclass
    class Record:
        id: str
        type: object
        value: str

    class MemoryBackend:
        def __init__(self) -> None:
            self.records = [
                Record("m1", SimpleNamespace(value="fact"), "prefers concise output")
            ]

        def list(self) -> list[Record]:
            return list(self.records)

        def delete(self, memory_id: str) -> bool:
            before = len(self.records)
            self.records = [record for record in self.records if record.id != memory_id]
            return len(self.records) != before

    (tmp_path / "notes.txt").write_text("safe metadata listing", encoding="utf-8")
    plane = DesktopControlPlane(provider_id="gemini", model_id="models/live")
    listener = DesktopControlListener(
        signing_key=b"unit-test-signing-key-32bytes!!",
        control_plane=plane,
        memory_backend=MemoryBackend(),
        files_root=tmp_path,
    )
    start = listener.handle(
        "POST",
        "/v1/pairing/start",
        body={"idempotency_key": "features-start"},
    )
    complete = listener.handle(
        "POST",
        "/v1/pairing/complete",
        body={
            "code": start.body["code"],
            "device_name": "iphone-features",
            "idempotency_key": "features-complete",
        },
    )
    token = listener.handle(
        "POST",
        "/v1/auth/token",
        body={
            "device_id": complete.body["device_id"],
            "device_secret": complete.body["device_secret"],
        },
    )
    headers = {"Authorization": f"Bearer {token.body['access_token']}"}

    models = listener.handle("GET", "/v1/models", headers=headers)
    assert _rows(models.body, "models")[0]["id"] == "models/live"
    rejected = listener.handle(
        "POST",
        "/v1/models/activate",
        headers=headers,
        body={"model_id": "invented", "idempotency_key": "model-reject"},
    )
    assert rejected.status_code == 409

    memory = listener.handle("GET", "/v1/memory", headers=headers)
    assert _rows(memory.body, "entries")[0]["summary"] == "prefers concise output"
    files = listener.handle("GET", "/v1/files", headers=headers, body={"path": "/"})
    assert _rows(files.body, "entries")[0]["name"] == "notes.txt"
    upload = listener.handle(
        "POST",
        "/v1/files/upload",
        headers=headers,
        body={
            "directory": str(tmp_path),
            "filename": "from-phone.txt",
            "content_base64": base64.b64encode(b"hello").decode("ascii"),
            "idempotency_key": "upload-live",
        },
    )
    assert upload.status_code == 201
    assert (tmp_path / "from-phone.txt").read_bytes() == b"hello"
    replay = listener.handle(
        "POST",
        "/v1/files/upload",
        headers=headers,
        body={
            "directory": str(tmp_path),
            "filename": "from-phone.txt",
            "content_base64": base64.b64encode(b"hello").decode("ascii"),
            "idempotency_key": "upload-live",
        },
    )
    assert replay.status_code == 201
    traversal = listener.handle(
        "POST",
        "/v1/files/upload",
        headers=headers,
        body={
            "directory": str(tmp_path),
            "filename": "../escape.txt",
            "content_base64": "aGVsbG8=",
            "idempotency_key": "upload-traversal",
        },
    )
    assert traversal.status_code == 400

    task = listener.handle(
        "POST",
        "/v1/tasks",
        headers=headers,
        body={"prompt": "inspect logs", "idempotency_key": "task-create-live"},
    )
    assert task.status_code == 202
    assert task.body["approval_required"] is True
    approvals = listener.handle("GET", "/v1/approvals", headers=headers)
    assert _rows(approvals.body, "approvals")[0]["tool_name"] == "agent_task"
    assert _rows(approvals.body, "approvals")[0]["intent"] == "inspect logs"


def test_listener_websocket_upgrade_streams_live_status() -> None:
    port = _free_loopback_port()
    plane = DesktopControlPlane(provider_id="gemini", model_id="models/live")
    listener = DesktopControlListener(
        bind_port=port,
        signing_key=b"unit-test-signing-key-32bytes!!",
        control_plane=plane,
    )
    start = listener.handle(
        "POST",
        "/v1/pairing/start",
        body={"idempotency_key": "ws-start"},
    )
    complete = listener.handle(
        "POST",
        "/v1/pairing/complete",
        body={
            "code": start.body["code"],
            "device_name": "iphone-ws",
            "idempotency_key": "ws-complete",
        },
    )
    token = listener.handle(
        "POST",
        "/v1/auth/token",
        body={
            "device_id": complete.body["device_id"],
            "device_secret": complete.body["device_secret"],
        },
    )
    listener.start()
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    sock.settimeout(2)
    try:
        websocket_key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET /v1/events HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {websocket_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {token.body['access_token']}\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = sock.recv(8192)
        if b"\r\n\r\n" not in response or b'"type": "status"' not in response:
            response += sock.recv(8192)
        assert b"101 Switching Protocols" in response
        assert b'"type": "status"' in response
        assert b'"model_id": "models/live"' in response
    finally:
        sock.close()
        listener.stop()


def test_runtime_safety_confirmation_roundtrips_through_approval_api() -> None:
    plane = DesktopControlPlane()
    listener = DesktopControlListener(
        signing_key=b"unit-test-signing-key-32bytes!!",
        control_plane=plane,
    )
    start = listener.handle(
        "POST",
        "/v1/pairing/start",
        body={"idempotency_key": "approval-start"},
    )
    complete = listener.handle(
        "POST",
        "/v1/pairing/complete",
        body={
            "code": start.body["code"],
            "device_name": "iphone-approval",
            "idempotency_key": "approval-complete",
        },
    )
    token = listener.handle(
        "POST",
        "/v1/auth/token",
        body={
            "device_id": complete.body["device_id"],
            "device_secret": complete.body["device_secret"],
        },
    )
    headers = {"Authorization": f"Bearer {token.body['access_token']}"}
    result: list[bool] = []
    worker = threading.Thread(
        target=lambda: result.append(
            plane.request_approval(
                "run_command",
                {"command": "safe-demo"},
                source="desktop_ui",
                reason="confirmation required",
            )
        )
    )
    worker.start()
    approval_id = ""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        approvals = listener.handle("GET", "/v1/approvals", headers=headers)
        rows = _rows(approvals.body, "approvals")
        if rows:
            approval_id = str(rows[0]["id"])
            break
        time.sleep(0.01)
    assert approval_id
    decision = listener.handle(
        "POST",
        f"/v1/approvals/{approval_id}/decision",
        headers=headers,
        body={"decision": "approve", "idempotency_key": "tool-approve"},
    )
    worker.join(timeout=2)
    assert decision.status_code == 200
    assert result == [True]


# --- CORS tests on the live listener ----------------------------------------


def test_health_endpoint_is_accessible_without_auth() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(bind_host="127.0.0.1", bind_port=port)
    listener.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 200
            body = json.loads(resp.read().decode("utf-8"))
            assert body["status"] == "ok"
            assert body["tls"] is False
    finally:
        listener.stop()


def test_cors_header_present_when_origin_whitelisted() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        cors_allowed_origins=["https://trusted.local"],
    )
    listener.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/status",
            method="GET",
            headers={"origin": "https://trusted.local"},
        )
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("expected 401 without auth")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            assert exc.headers.get("Access-Control-Allow-Origin") == "https://trusted.local"
    finally:
        listener.stop()


def test_cors_header_not_present_for_unknown_origin() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        cors_allowed_origins=["https://trusted.local"],
    )
    listener.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/status",
            method="GET",
            headers={"origin": "https://unknown.local"},
        )
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("expected 401 without auth")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
            assert exc.headers.get("Access-Control-Allow-Origin") is None
    finally:
        listener.stop()


def test_cors_preflight_returns_204_with_allowed_origin() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        cors_allowed_origins=["https://trusted.local"],
    )
    listener.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/health",
            method="OPTIONS",
            headers={"origin": "https://trusted.local"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 204
            assert resp.headers.get("Access-Control-Allow-Origin") == "https://trusted.local"
            assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "")
            assert "POST" in resp.headers.get("Access-Control-Allow-Methods", "")
            assert "Content-Type" in resp.headers.get("Access-Control-Allow-Headers", "")
    finally:
        listener.stop()


def test_cors_preflight_rejected_for_unknown_origin() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        cors_allowed_origins=["https://trusted.local"],
    )
    listener.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/health",
            method="OPTIONS",
            headers={"origin": "https://untrusted.local"},
        )
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("expected 403 for untrusted origin")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        listener.stop()


def test_health_on_whitelisted_origin_includes_cors_header() -> None:
    port = _free_loopback_port()
    listener = DesktopControlListener(
        bind_host="127.0.0.1",
        bind_port=port,
        cors_allowed_origins=["https://trusted.local"],
    )
    listener.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/health",
            method="GET",
            headers={"origin": "https://trusted.local"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            assert resp.status == 200
            body = json.loads(resp.read().decode("utf-8"))
            assert body["status"] == "ok"
            assert resp.headers.get("Access-Control-Allow-Origin") == "https://trusted.local"
    finally:
        listener.stop()
