from __future__ import annotations

from providers.local import (
    FACTORY_IDS,
    LlamaCppChatProvider,
    OllamaChatProvider,
    OpenAICompatibleChatProvider,
    register_factories,
)
from providers.registry import get, registered_ids

from tests.unit.providers.local.fakes import ollama_transport, openai_transport


def test_four_factory_ids_are_registered(clean_registry) -> None:
    register_factories()
    ids = registered_ids()
    assert FACTORY_IDS == ("local", "ollama", "llama_cpp", "openai_compat")
    for provider_id in FACTORY_IDS:
        assert provider_id in ids
        assert callable(get(provider_id))


def test_factories_construct_matching_providers(clean_registry) -> None:
    register_factories()
    local = get("local")(transport=openai_transport())
    ollama = get("ollama")(transport=ollama_transport())
    llama = get("llama_cpp")(transport=openai_transport())
    compat = get("openai_compat")(base_url="http://127.0.0.1:8080/v1", transport=openai_transport())
    assert isinstance(local, OpenAICompatibleChatProvider)
    assert isinstance(ollama, OllamaChatProvider)
    assert isinstance(llama, LlamaCppChatProvider)
    assert isinstance(compat, OpenAICompatibleChatProvider)
    assert compat.provider_id == "openai_compat"
