"""Gemini provider package. Importing this module registers factory id ``gemini``."""

from __future__ import annotations

from providers.gemini.catalog import PROVIDER_ID
from providers.gemini.provider import GeminiChatProvider
from providers.registry import register

register(PROVIDER_ID, GeminiChatProvider)

__all__ = ["GeminiChatProvider", "PROVIDER_ID"]
