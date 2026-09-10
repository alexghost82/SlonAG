"""Adversarial offline: any non-loopback connect must fail the test."""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import pytest

from memory.memory_manager import extract_memory, should_extract_memory

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _guarded_create_connection(
    original: Callable[..., Any],
) -> Callable[..., Any]:
    def _wrapped(address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        host_s = str(host)
        if host_s not in _LOOPBACK:
            raise AssertionError(f"non-loopback connect forbidden offline: {host_s}")
        return original(address, *args, **kwargs)

    return _wrapped


@pytest.fixture
def offline_connect_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "memory.memory_manager._memory_cloud_forbidden",
        lambda: True,
    )
    original = socket.create_connection
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection(original))

    try:
        import requests

        original_req = requests.sessions.Session.request

        def _req(self: Any, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
            host = url.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
            if host not in _LOOPBACK:
                raise AssertionError(f"non-loopback requests forbidden offline: {url}")
            return original_req(self, method, url, *args, **kwargs)

        monkeypatch.setattr(requests.sessions.Session, "request", _req)
    except ImportError:
        pass

    try:
        import httpx

        original_httpx = httpx.Client.request

        def _httpx(self: Any, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:
            text = str(url)
            host = text.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
            if host not in _LOOPBACK:
                raise AssertionError(f"non-loopback httpx forbidden offline: {text}")
            return original_httpx(self, method, url, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "request", _httpx)
    except ImportError:
        pass

    try:
        import aiohttp

        original_aio = aiohttp.ClientSession._request

        async def _aio(self: Any, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:
            text = str(url)
            host = text.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
            if host not in _LOOPBACK:
                raise AssertionError(f"non-loopback aiohttp forbidden offline: {text}")
            return await original_aio(self, method, url, *args, **kwargs)

        monkeypatch.setattr(aiohttp.ClientSession, "_request", _aio)
    except ImportError:
        pass


def test_harness_rejects_non_loopback(offline_connect_guard: None) -> None:
    with pytest.raises(AssertionError, match="non-loopback"):
        socket.create_connection(("1.1.1.1", 443), timeout=0.2)


def test_memory_extract_is_noop_offline(offline_connect_guard: None) -> None:
    assert should_extract_memory("My name is Alex") is False
    assert extract_memory("My name is Alex") == {}


def test_loopback_still_allowed(offline_connect_guard: None) -> None:
    # Connecting may fail if nothing listens; it must not trip the guard.
    try:
        socket.create_connection(("127.0.0.1", 9), timeout=0.2)
    except OSError:
        pass


def test_live_factory_fail_closed_offline(offline_connect_guard: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("config.schema.settings_forbid_cloud", lambda settings=None: True)
    from providers.gemini.live import create_live_client

    with pytest.raises(RuntimeError, match="disabled"):
        create_live_client(api_key="test-key")
