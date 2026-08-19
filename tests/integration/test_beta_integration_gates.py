"""Integration beta gates: Desktop API + NetworkPolicy × SafetyPolicy.

In-process only. No live HTTP listeners, no DNS, no cloud calls.
"""

from __future__ import annotations

import json
import socket

from mark.network import NetworkMode, NetworkPolicy
from mark.safety import UnsafeUrlError, check_url
from server import DesktopControlApp
from server.app import BindHostError
from server.schemas import CODE_UNAUTHORIZED

CLOUD_IDS = ("gemini", "openai", "openrouter")


def test_desktop_api_defaults_to_loopback_and_rejects_public_bind() -> None:
    app = DesktopControlApp()
    assert app.bind_host == "127.0.0.1"
    assert app.allow_non_loopback is False
    assert app.listening is False
    for host in ("0.0.0.0", "8.8.8.8", "192.168.1.1"):
        try:
            DesktopControlApp(bind_host=host)
        except BindHostError:
            continue
        raise AssertionError(f"expected BindHostError for {host}")


def test_desktop_api_unauthenticated_status_is_401() -> None:
    app = DesktopControlApp()
    response = app.handle("GET", "/v1/status")
    assert response.status_code == 401
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_UNAUTHORIZED


def test_desktop_api_mock_does_not_listen_on_socket() -> None:
    finder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        finder.bind(("127.0.0.1", 0))
        port = int(finder.getsockname()[1])
    finally:
        finder.close()

    app = DesktopControlApp(bind_host="127.0.0.1", bind_port=port)
    assert app.listening is False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_authenticated_status_omits_api_key_fields() -> None:
    app = DesktopControlApp()
    response = app.handle(
        "GET",
        "/v1/status",
        headers={"Authorization": "Bearer device-token"},
    )
    assert response.status_code == 200
    blob = json.dumps(response.body, sort_keys=True)
    for name in ("api_key", "gemini_api_key", "openai_api_key", "openrouter_api_key"):
        assert name not in response.body
        assert f'"{name}"' not in blob


def test_offline_network_and_safety_block_cloud_and_ssrf() -> None:
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE)
    for provider_id in CLOUD_IDS:
        assert policy.allows_cloud_provider(provider_id) is False

    denied = policy.check_request(
        url="https://api.openai.com/v1/chat/completions",
        tool="chat",
        purpose="integration_gate",
    )
    assert denied.allowed is False

    loopback = policy.check_request(url="http://127.0.0.1:11434/api/tags")
    assert loopback.allowed is True

    try:
        check_url("http://169.254.169.254/latest/meta-data")
    except UnsafeUrlError:
        return
    raise AssertionError("expected UnsafeUrlError for metadata SSRF URL")
