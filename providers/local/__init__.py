"""Local OpenAI-compatible, Ollama, llama.cpp, and generic OpenAI-compatible chat adapters."""

from __future__ import annotations

from providers.local.capabilities import (
    LocalModelCapabilities,
    resolve_local_capabilities,
)
from providers.local.common import (
    DEFAULT_LLAMA_CPP_BASE_URL,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_OLLAMA_BASE_URL,
)
from providers.local.endpoint import is_loopback_url
from providers.local.http import TransportResponse
from providers.local.llama_cpp import LlamaCppChatProvider
from providers.local.ollama import OllamaChatProvider
from providers.local.openai_compatible import OpenAICompatibleChatProvider
from providers.registry import register

FACTORY_IDS = ("local", "ollama", "llama_cpp", "openai_compat")


def register_factories() -> None:
    """Register the four local factory ids. Safe to call more than once."""
    register("local", OpenAICompatibleChatProvider)
    register("ollama", OllamaChatProvider)
    register("llama_cpp", LlamaCppChatProvider)
    # openai_compat: factory that returns an instance with provider_id="openai_compat"
    def _openai_compat_factory(**kwargs):
        instance = OpenAICompatibleChatProvider(**kwargs)
        instance.provider_id = "openai_compat"
        return instance
    register("openai_compat", _openai_compat_factory)


register_factories()

__all__ = [
    "DEFAULT_LLAMA_CPP_BASE_URL",
    "DEFAULT_LOCAL_BASE_URL",
    "DEFAULT_OLLAMA_BASE_URL",
    "FACTORY_IDS",
    "LlamaCppChatProvider",
    "LocalModelCapabilities",
    "OllamaChatProvider",
    "OpenAICompatibleChatProvider",
    "TransportResponse",
    "is_loopback_url",
    "register_factories",
]
