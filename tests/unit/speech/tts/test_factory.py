"""Factory registration for ``tts_local``."""

from __future__ import annotations

import importlib

from providers.contracts import TextToSpeechProvider
from providers.registry import get, registered_ids
from speech.tts.provider import LocalTTSProvider

from tests.unit.speech.tts.fakes import RecordingEngine


def test_factory_tts_local_is_registered(clean_registry) -> None:
    import speech.tts as tts_pkg

    importlib.reload(tts_pkg)
    assert tts_pkg.PROVIDER_ID == "tts_local"
    assert "tts_local" in registered_ids()
    factory = get("tts_local")
    provider = factory(engine=RecordingEngine(), voice="anna")
    assert factory is tts_pkg.LocalTTSProvider
    assert isinstance(provider, LocalTTSProvider)
    assert isinstance(provider, TextToSpeechProvider)
    assert provider.provider_id == "tts_local"


def test_register_factory_is_idempotent(clean_registry) -> None:
    import speech.tts as tts_pkg

    importlib.reload(tts_pkg)
    tts_pkg.register_factory()
    tts_pkg.register_factory()
    assert get("tts_local") is tts_pkg.LocalTTSProvider
