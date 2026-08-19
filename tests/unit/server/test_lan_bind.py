"""Unit tests for same-LAN bind policy (no real socket listen)."""

from __future__ import annotations

import pytest

from server.app import DesktopControlApp
from server.bind_policy import (
    BindHostError,
    is_forbidden_wildcard_bind,
    is_same_lan_bind_host,
    validate_bind_host,
)
from server.schemas import CODE_UNAUTHORIZED


def test_validate_default_loopback() -> None:
    assert validate_bind_host("127.0.0.1") == "127.0.0.1"
    assert validate_bind_host("localhost") == "localhost"


@pytest.mark.parametrize(
    "host",
    ("0.0.0.0", "::", "[::]", "8.8.8.8", "192.168.1.1", "10.0.0.5"),
)
def test_validate_rejects_non_loopback_without_opt_in(host: str) -> None:
    with pytest.raises(BindHostError):
        validate_bind_host(host, allow_non_loopback=False)


@pytest.mark.parametrize(
    "host",
    (
        "192.168.1.10",
        "10.0.0.2",
        "172.16.5.5",
        "172.31.255.1",
    ),
)
def test_validate_allows_rfc1918_with_opt_in(host: str) -> None:
    assert validate_bind_host(host, allow_non_loopback=True) == host
    assert is_same_lan_bind_host(host) is True


@pytest.mark.parametrize("host", ("0.0.0.0", "::", "[::]"))
def test_validate_always_rejects_wildcards(host: str) -> None:
    assert is_forbidden_wildcard_bind(host) is True
    with pytest.raises(BindHostError):
        validate_bind_host(host, allow_non_loopback=True)


@pytest.mark.parametrize("host", ("8.8.8.8", "1.1.1.1", "9.9.9.9"))
def test_validate_rejects_public_even_with_opt_in(host: str) -> None:
    with pytest.raises(BindHostError):
        validate_bind_host(host, allow_non_loopback=True)


def test_app_same_lan_opt_in() -> None:
    app = DesktopControlApp(bind_host="192.168.0.42", allow_non_loopback=True)
    assert app.bind_host == "192.168.0.42"
    assert app.allow_non_loopback is True
    assert app.listening is False


def test_app_rejects_public_with_opt_in() -> None:
    with pytest.raises(BindHostError):
        DesktopControlApp(bind_host="8.8.8.8", allow_non_loopback=True)


def test_app_rejects_wildcard_with_opt_in() -> None:
    with pytest.raises(BindHostError):
        DesktopControlApp(bind_host="0.0.0.0", allow_non_loopback=True)


def test_lan_bind_does_not_weaken_auth() -> None:
    """Same-LAN configuration still requires Authorization on protected routes."""
    app = DesktopControlApp(bind_host="10.0.0.8", allow_non_loopback=True)
    response = app.handle("GET", "/v1/status")
    assert response.status_code == 401
    error = response.body["error"]
    assert isinstance(error, dict)
    assert error["code"] == CODE_UNAUTHORIZED

    ok = app.handle(
        "GET",
        "/v1/status",
        headers={"Authorization": "Bearer device-token"},
    )
    assert ok.status_code == 200
