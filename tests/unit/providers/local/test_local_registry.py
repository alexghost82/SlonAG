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


def test_three_factory_ids_are_registered(clean_registry) -> None:
    register_factories()
    ids = registered_ids()
    assert FACTORY_IDS == ("local", "ollama", "llama_cpp")
    for provider_id in FACTORY_IDS:
        assert provider_id in ids
        assert callable(get(provider_id))


def test_factories_construct_matching_providers(clean_registry) -> None:
    register_factories()
    local = get("local")(transport=openai_transport())
    ollama = get("ollama")(transport=ollama_transport())
    llama = get("llama_cpp")(transport=openai_transport())
    assert isinstance(local, OpenAICompatibleChatProvider)
    assert isinstance(ollama, OllamaChatProvider)
    assert isinstance(llama, LlamaCppChatProvider)
    assert local.provider_id == "local"
    assert ollama.provider_id == "ollama"
    assert llama.provider_id == "llama_cpp"
