"""Unit tests for loopback bind rules and in-process mock dispatcher."""

from __future__ import annotations

try:
    import tkinter  # noqa: F401
    _HAS_TKINTER = True
except ImportError:
    _HAS_TKINTER = False

import json
import socket

import pytest

from server import DesktopControlApp, MockDesktopApi
from server.app import BindHostError, MockResponse
from server.schemas import CODE_UNAUTHORIZED


def test_default_bind_is_loopback() -> None:
    app = DesktopControlApp()
    assert app.bind_host == "127.0.0.1"
    assert app.allow_non_loopback is False
    assert app.listening is False


@pytest.mark.parametrize("host", ("0.0.0.0", "::", "[::]", "8.8.8.8", "192.168.1.1"))
def test_default_bind_rejects_non_loopback(host: str) -> None:
    with pytest.raises(BindHostError):
        DesktopControlApp(bind_host=host)


def test_explicit_allow_non_loopback_opt_in() -> None:
    app = DesktopControlApp(bind_host="192.168.1.10", allow_non_loopback=True)
    assert app.bind_host == "192.168.1.10"


def test_opt_in_still_rejects_public_and_wildcard() -> None:
    with pytest.raises(BindHostError):
        DesktopControlApp(bind_host="8.8.8.8", allow_non_loopback=True)
    with pytest.raises(BindHostError):
        DesktopControlApp(bind_host="0.0.0.0", allow_non_loopback=True)


def test_mock_alias_is_same_type() -> None:
    assert MockDesktopApi is DesktopControlApp


def test_unauthenticated_status_returns_401() -> None:
    app = DesktopControlApp()
    response = app.handle("GET", "/v1/status")
    assert response.status_code == 401
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_UNAUTHORIZED


def test_unauthenticated_events_returns_401() -> None:
    app = DesktopControlApp()
    for method in ("GET", "WS"):
        response = app.handle(method, "/v1/events")
        assert response.status_code == 401


@pytest.mark.skipif(not _HAS_TKINTER, reason="tkinter not available")
def test_authenticated_status_ok_without_api_keys() -> None:
    app = DesktopControlApp()
    response = app.handle(
        "GET",
        "/v1/status",
        headers={"Authorization": "Bearer device-token"},
    )
    assert response.status_code == 200
    _assert_no_api_key_material(response)


def test_chat_idempotency_no_double_side_effect() -> None:
    app = DesktopControlApp()
    body = {
        "message": "hello",
        "idempotency_key": "chat-1",
        "api_key": "sk-should-never-echo",
        "gemini_api_key": "should-not-appear",
        "openrouter_api_key": "should-not-appear",
    }
    first = app.handle("POST", "/v1/chat", body=body)
    second = app.handle("POST", "/v1/chat", body=body)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.body == second.body
    assert first.body.get("approval_required") is True
    assert app.side_effect_count("chat:chat-1") == 1
    _assert_no_api_key_material(first)
    _assert_no_api_key_material(second)


def test_tasks_create_idempotency() -> None:
    app = DesktopControlApp()
    body = {"prompt": "plan", "idempotency_key": "task-1"}
    first = app.handle("POST", "/v1/tasks", body=body)
    second = app.handle("POST", "/v1/tasks", body=body)
    assert first.body == second.body
    assert first.body.get("approval_required") is True
    assert app.side_effect_count("tasks_create:task-1") == 1


def test_mutating_routes_require_idempotency_key() -> None:
    app = DesktopControlApp()
    response = app.handle("POST", "/v1/chat", body={"message": "hi"})
    assert response.status_code == 400
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == "missing_field"


def test_responses_never_include_api_key_fields() -> None:
    app = DesktopControlApp()
    routes: list[tuple[str, str, dict[str, object] | None]] = [
        ("POST", "/v1/pairing/start", {"idempotency_key": "p1"}),
        (
            "POST",
            "/v1/pairing/complete",
            {
                "code": "123456",
                "device_name": "phone",
                "idempotency_key": "p2",
                "openrouter_api_key": "leak",
            },
        ),
        ("POST", "/v1/chat", {"message": "x", "idempotency_key": "c1"}),
        ("POST", "/v1/tasks", {"prompt": "x", "idempotency_key": "t1"}),
        ("POST", "/v1/tasks/abc/cancel", {"idempotency_key": "tc1"}),
        (
            "POST",
            "/v1/approvals/a1/decision",
            {"decision": "deny", "idempotency_key": "d1"},
        ),
        ("POST", "/v1/models/activate", {"model_id": "m1", "idempotency_key": "m1"}),
        ("POST", "/v1/screen/capture", {"idempotency_key": "s1"}),
        ("DELETE", "/v1/memory/mem1", {"idempotency_key": "del1"}),
        ("GET", "/v1/models", None),
        ("GET", "/v1/memory", None),
        ("GET", "/v1/tasks", None),
        ("GET", "/v1/approvals", None),
    ]
    for method, path, body in routes:
        response = app.handle(method, path, body=body)
        assert response.status_code < 500
        _assert_no_api_key_material(response)


def test_no_real_socket_listen() -> None:
    finder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        finder.bind(("127.0.0.1", 0))
        port = int(finder.getsockname()[1])
    finally:
        finder.close()

    app = DesktopControlApp(bind_host="127.0.0.1", bind_port=port)
    assert app.listening is False
    # Same port must still be bindable — mock must not have listen()'d.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def _assert_no_api_key_material(response: MockResponse) -> None:
    forbidden = {
        "api_key",
        "gemini_api_key",
        "openai_api_key",
        "openrouter_api_key",
    }
    blob = json.dumps(response.body, sort_keys=True)
    for name in forbidden:
        assert name not in response.body
        assert f'"{name}"' not in blob
    assert "sk-should-never-echo" not in blob
    assert "sk-" not in blob
