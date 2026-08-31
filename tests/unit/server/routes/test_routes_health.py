"""Unit tests for /v1/health endpoint and health_check handler."""

from __future__ import annotations

import time

from server.routes.status import health_check


def test_health_check_returns_200_with_ok_status() -> None:
    response = health_check(
        is_listening=True,
        tls_enabled=False,
        bind_host="127.0.0.1",
        bind_port=8765,
    )
    assert response.status_code == 200
    assert response.body["status"] == "ok"


def test_health_check_status_becomes_starting_when_not_listening() -> None:
    response = health_check(is_listening=False)
    assert response.body["status"] == "starting"


def test_health_check_excludes_secrets() -> None:
    response = health_check(is_listening=True)
    for key in response.body:
        assert key not in (
            "api_key",
            "gemini_api_key",
            "openai_api_key",
            "openrouter_api_key",
            "raw_key",
            "secret_key",
        )


def test_health_check_includes_tls_flag() -> None:
    response_true = health_check(is_listening=True, tls_enabled=True)
    assert response_true.body["tls"] is True

    response_false = health_check(is_listening=True, tls_enabled=False)
    assert response_false.body["tls"] is False


def test_health_check_includes_bind_info() -> None:
    response = health_check(
        is_listening=True,
        bind_host="0.0.0.0",
        bind_port=9999,
    )
    assert response.body["bind_host"] == "0.0.0.0"
    assert response.body["bind_port"] == 9999


def test_health_check_includes_uptime() -> None:
    start = time.monotonic()
    response = health_check(is_listening=True, uptime=123.45)
    assert response.body["uptime_seconds"] == 123.45


def test_health_check_uses_injected_provider() -> None:
    def provider() -> dict[str, object]:
        return {"custom_field": "value", "paired": True}

    response = health_check(is_listening=True, provider=provider)
    assert response.body["custom_field"] == "value"
    assert response.body["paired"] is True
