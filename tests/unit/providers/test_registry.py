from __future__ import annotations

import pytest

from providers.errors import ProviderError
from providers.registry import clear, get, register, registered_ids

from tests.unit.providers.mocks import MockChatProvider


def test_register_and_get_returns_factory(clean_registry) -> None:
    def factory() -> MockChatProvider:
        return MockChatProvider("gemini")

    register("gemini", factory)
    assert get("gemini") is factory
    assert registered_ids() == ("gemini",)


def test_get_unknown_id_raises(clean_registry) -> None:
    with pytest.raises(ProviderError, match="unknown provider_id") as exc_info:
        get("not-registered")
    assert "not-registered" in str(exc_info.value)


def test_registered_ids_are_sorted(clean_registry) -> None:
    register("openrouter", lambda: MockChatProvider("openrouter"))
    register("gemini", lambda: MockChatProvider("gemini"))
    register("local", lambda: MockChatProvider("local"))
    assert registered_ids() == ("gemini", "local", "openrouter")


def test_get_does_not_instantiate_factory(clean_registry) -> None:
    calls = {"n": 0}

    def factory() -> MockChatProvider:
        calls["n"] += 1
        return MockChatProvider("openai")

    register("openai", factory)
    retrieved = get("openai")
    assert retrieved is factory
    assert calls["n"] == 0
    assert isinstance(retrieved(), MockChatProvider)
    assert calls["n"] == 1


def test_clear_removes_registrations(clean_registry) -> None:
    register("local", lambda: MockChatProvider("local"))
    clear()
    assert registered_ids() == ()
    with pytest.raises(ProviderError):
        get("local")


def test_register_rejects_empty_id(clean_registry) -> None:
    with pytest.raises(ProviderError, match="provider_id"):
        register("", lambda: MockChatProvider("gemini"))
