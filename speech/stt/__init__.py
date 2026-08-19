"""Local STT package. Importing this module registers factory id ``stt_local``."""

from __future__ import annotations

from providers.registry import register
from speech.stt.provider import (
    DEFAULT_LANGUAGE,
    PROVIDER_ID,
    LocalSTTProvider,
    STTEngine,
)

register(PROVIDER_ID, LocalSTTProvider)

__all__ = [
    "DEFAULT_LANGUAGE",
    "PROVIDER_ID",
    "LocalSTTProvider",
    "STTEngine",
]
