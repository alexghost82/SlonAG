"""Ollama native chat adapter."""

from __future__ import annotations

from providers.local.common import (
    DEFAULT_OLLAMA_BASE_URL,
    PROTOCOL_OLLAMA,
    BaseLocalChatProvider,
)
from providers.local.http import Transport


class OllamaChatProvider(BaseLocalChatProvider):
    """Ollama runtime using ``/api/tags`` and ``/api/chat``."""

    provider_id = "ollama"
    default_base_url = DEFAULT_OLLAMA_BASE_URL
    models_path = "/api/tags"
    chat_path = "/api/chat"
    protocol = PROTOCOL_OLLAMA

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
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
