from __future__ import annotations

import pytest

from providers.errors import ProviderOfflineError
from providers.local import (
    DEFAULT_LLAMA_CPP_BASE_URL,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_OLLAMA_BASE_URL,
    LlamaCppChatProvider,
    OllamaChatProvider,
    OpenAICompatibleChatProvider,
    is_loopback_url,
)
from providers.local.endpoint import is_loopback_host

from tests.unit.providers.local.fakes import FakeTransport, openai_transport

PROVIDERS = (
    OpenAICompatibleChatProvider,
    OllamaChatProvider,
    LlamaCppChatProvider,
)


def test_default_urls_are_loopback() -> None:
    local = OpenAICompatibleChatProvider(transport=openai_transport())
    ollama = OllamaChatProvider(transport=openai_transport())
    llama = LlamaCppChatProvider(transport=openai_transport())

    assert local.base_url == DEFAULT_LOCAL_BASE_URL
    assert ollama.base_url == DEFAULT_OLLAMA_BASE_URL
    assert llama.base_url == DEFAULT_LLAMA_CPP_BASE_URL
    assert DEFAULT_LOCAL_BASE_URL == "http://127.0.0.1:8080/v1"
    assert DEFAULT_OLLAMA_BASE_URL == "http://127.0.0.1:11434"
    assert DEFAULT_LLAMA_CPP_BASE_URL == "http://127.0.0.1:8080"
    assert is_loopback_url(local.base_url)
    assert is_loopback_url(ollama.base_url)
    assert is_loopback_url(llama.base_url)


@pytest.mark.parametrize("factory", PROVIDERS)
def test_example_com_rejected_when_remote_disallowed(factory) -> None:
    transport = FakeTransport()
    with pytest.raises(ProviderOfflineError, match="example.com") as exc_info:
        factory(base_url="http://example.com", transport=transport)
    assert transport.calls == []
    assert exc_info.value.provider_id == factory.provider_id


@pytest.mark.parametrize("factory", PROVIDERS)
def test_public_dns_and_ip_rejected_when_remote_disallowed(factory) -> None:
    transport = FakeTransport()
    for url in (
        "http://example.com/v1",
        "https://example.com",
        "http://8.8.8.8:8080",
        "http://192.168.1.10",
    ):
        with pytest.raises(ProviderOfflineError):
            factory(base_url=url, allow_remote=False, transport=transport)
    assert transport.calls == []


@pytest.mark.parametrize("factory", PROVIDERS)
@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1:9999",
        "http://localhost:11434",
        "http://[::1]:8080",
        "http://127.1.2.3/v1",
    ),
)
def test_loopback_hosts_are_allowed(factory, url: str) -> None:
    provider = factory(base_url=url, transport=openai_transport())
    assert is_loopback_url(provider.base_url)


@pytest.mark.parametrize("factory", PROVIDERS)
def test_allow_remote_permits_example_com_without_http(factory) -> None:
    transport = FakeTransport()
    provider = factory(
        base_url="http://example.com",
        allow_remote=True,
        transport=transport,
    )
    assert provider.base_url == "http://example.com"
    assert transport.calls == []


def test_loopback_host_helper_rejects_non_localhost_dns() -> None:
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("::1") is True
    assert is_loopback_host("example.com") is False
    assert is_loopback_host("localhost.example.com") is False
