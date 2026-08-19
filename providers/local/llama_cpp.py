"""llama.cpp server chat adapter (OpenAI-compatible HTTP)."""

from __future__ import annotations

from providers.local.common import DEFAULT_LLAMA_CPP_BASE_URL, PROTOCOL_OPENAI
from providers.local.http import Transport
from providers.local.openai_compatible import OpenAICompatibleChatProvider


class LlamaCppChatProvider(OpenAICompatibleChatProvider):
    """llama.cpp server on loopback, talking to ``/v1/models``."""

    provider_id = "llama_cpp"
    default_base_url = DEFAULT_LLAMA_CPP_BASE_URL
    models_path = "/v1/models"
    chat_path = "/v1/chat/completions"
    protocol = PROTOCOL_OPENAI

    def __init__(
        self,
        base_url: str = DEFAULT_LLAMA_CPP_BASE_URL,
        api_key: str | None = None,
        *,
        allow_remote: bool = False,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(
            base_url,
            api_key,
            allow_remote=allow_remote,
            transport=transport,
        )
