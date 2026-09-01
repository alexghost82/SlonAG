from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace

from providers.contracts import (
    AudioRequest,
    ModelInfo,
    SpeechToTextProvider,
    Transcript,
)
from providers.registry import get
from speech.stt.engines import OptionalFasterWhisperEngine
from speech.stt.provider import DEFAULT_LANGUAGE, PROVIDER_ID, LocalSTTProvider

from tests.unit.speech.stt.fakes import ExplodingEngine, FakeEngine, PartialEngine

AUDIO = b"RIFF\x00\x00\x00\x00WAVEfake"


def _model() -> ModelInfo:
    return ModelInfo(
        provider_id=PROVIDER_ID,
        model_id="local-stt",
        display_name="Local STT",
        audio_input=True,
        local=True,
    )


def _request(audio: bytes = AUDIO) -> AudioRequest:
    return AudioRequest(model=_model(), audio=audio)


def test_default_language_is_russian() -> None:
    provider = LocalSTTProvider(FakeEngine())
    assert provider.language == "ru"
    assert DEFAULT_LANGUAGE == "ru"


async def test_transcribe_forwards_default_language_to_engine() -> None:
    engine = FakeEngine(text="распознано")
    provider = LocalSTTProvider(engine)
    result = await provider.transcribe(_request())
    assert result == Transcript(text="распознано")
    assert engine.calls == [(AUDIO, "ru")]


async def test_custom_language_is_forwarded() -> None:
    engine = FakeEngine()
    provider = LocalSTTProvider(engine, language="en")
    await provider.transcribe(_request())
    assert engine.calls == [(AUDIO, "en")]


async def test_echo_guard_skips_engine() -> None:
    engine = ExplodingEngine()
    provider = LocalSTTProvider(engine, is_assistant_speaking=lambda: True)
    result = await provider.transcribe(_request())
    assert result == Transcript(text="")


async def test_echo_guard_false_calls_engine() -> None:
    engine = FakeEngine(text="команда")
    provider = LocalSTTProvider(engine, is_assistant_speaking=lambda: False)
    result = await provider.transcribe(_request())
    assert result.text == "команда"
    assert len(engine.calls) == 1


async def test_cancel_prevents_engine_and_returns_empty() -> None:
    engine = ExplodingEngine()
    provider = LocalSTTProvider(engine)
    provider.cancel()
    result = await provider.transcribe(_request())
    assert result == Transcript(text="")


async def test_cancelled_event_skips_engine() -> None:
    engine = ExplodingEngine()
    flag = threading.Event()
    flag.set()
    provider = LocalSTTProvider(engine, cancelled=flag)
    result = await provider.transcribe(_request())
    assert result == Transcript(text="")


async def test_cancelled_callable_skips_engine() -> None:
    engine = ExplodingEngine()
    provider = LocalSTTProvider(engine, cancelled=lambda: True)
    result = await provider.transcribe(_request())
    assert result == Transcript(text="")


async def test_vad_false_skips_engine() -> None:
    engine = ExplodingEngine()
    provider = LocalSTTProvider(engine, vad_detect=lambda audio: False)
    result = await provider.transcribe(_request())
    assert result == Transcript(text="")
    assert isinstance(result, Transcript)


async def test_vad_true_calls_engine() -> None:
    engine = FakeEngine(text="есть речь")
    seen: list[bytes] = []

    def detect(audio: bytes) -> bool:
        seen.append(audio)
        return True

    provider = LocalSTTProvider(engine, vad_detect=detect)
    result = await provider.transcribe(_request())
    assert result.text == "есть речь"
    assert seen == [AUDIO]
    assert len(engine.calls) == 1


async def test_interim_callback_receives_engine_partials() -> None:
    engine = PartialEngine()
    partials: list[str] = []
    provider = LocalSTTProvider(engine, on_partial=partials.append)
    result = await provider.transcribe(_request())
    assert result.text == "привет"
    assert partials == ["при", "привет"]
    assert engine.calls == [(AUDIO, "ru")]


async def test_cancel_during_partials_returns_partial_and_stops() -> None:
    engine = PartialEngine(partials=("раз", "два", "три"), text="три")
    emitted: list[str] = []

    def on_partial(text: str) -> None:
        emitted.append(text)
        if text == "два":
            provider.cancel()

    provider = LocalSTTProvider(engine, on_partial=on_partial)
    result = await provider.transcribe(_request())
    assert result.text == "два"
    assert emitted == ["раз", "два"]


def test_package_import_registers_stt_local_factory() -> None:
    import speech.stt as stt_pkg

    importlib.reload(stt_pkg)
    factory = get("stt_local")
    provider = factory(engine=FakeEngine())
    assert factory is stt_pkg.LocalSTTProvider
    assert isinstance(provider, stt_pkg.LocalSTTProvider)
    assert isinstance(provider, SpeechToTextProvider)
    assert stt_pkg.PROVIDER_ID == "stt_local"


def test_faster_whisper_engine_uses_fast_command_settings() -> None:
    calls: list[dict[str, object]] = []

    class FakeModel:
        def transcribe(self, _path: str, **kwargs: object):
            calls.append(kwargs)
            return iter((SimpleNamespace(text=" включи "), SimpleNamespace(text=" свет "))), None

    class FakeModule:
        @staticmethod
        def WhisperModel(*_args: object, **_kwargs: object) -> FakeModel:
            return FakeModel()

    engine = OptionalFasterWhisperEngine(module=FakeModule())
    assert engine.transcribe(AUDIO, "ru") == "включи свет"
    assert calls == [
        {
            "language": "ru",
            "beam_size": 1,
            "vad_filter": True,
            "condition_on_previous_text": False,
        }
    ]


def test_faster_whisper_engine_disables_network_model_downloads() -> None:
    seen: dict[str, object] = {}

    class FakeModule:
        @staticmethod
        def WhisperModel(*_args: object, **kwargs: object) -> object:
            seen.update(kwargs)
            return object()

    OptionalFasterWhisperEngine(module=FakeModule())._load()
    assert seen["local_files_only"] is True
