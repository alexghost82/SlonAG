"""Generic OpenAI-compatible local chat adapter."""

from __future__ import annotations

from providers.local.common import (
    DEFAULT_LOCAL_BASE_URL,
    PROTOCOL_OPENAI,
    BaseLocalChatProvider,
)
from providers.local.http import Transport


class OpenAICompatibleChatProvider(BaseLocalChatProvider):
    """Local OpenAI-compatible runtime (LM Studio, vLLM, generic /v1)."""

    provider_id = "local"
    default_base_url = DEFAULT_LOCAL_BASE_URL
    models_path = "/v1/models"
    chat_path = "/v1/chat/completions"
    protocol = PROTOCOL_OPENAI

    def __init__(
        self,
        base_url: str = DEFAULT_LOCAL_BASE_URL,
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
