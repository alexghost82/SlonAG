"""Local TTS package. Importing this module registers factory id ``tts_local``."""

from __future__ import annotations

from providers.registry import register
from speech.tts.normalize import normalize_tts_text, number_to_ru
from speech.tts.provider import LocalTTSProvider, SpeechSynthesizer
from speech.tts.sentences import split_sentences

PROVIDER_ID = "tts_local"


def register_factory() -> None:
    """Register factory id ``tts_local``. Safe to call more than once."""
    register(PROVIDER_ID, LocalTTSProvider)


register_factory()

__all__ = [
    "PROVIDER_ID",
    "LocalTTSProvider",
    "SpeechSynthesizer",
    "normalize_tts_text",
    "number_to_ru",
    "register_factory",
    "split_sentences",
]
