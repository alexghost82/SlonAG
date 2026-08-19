"""LocalTTSProvider: sentence streaming, barge-in, preview, echo-guard."""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from providers.contracts import (
    AudioStream,
    ModelInfo,
    SpeechRequest,
    TextToSpeechProvider,
)
from speech.tts.provider import LocalTTSProvider
from speech.tts.sentences import split_sentences

from tests.unit.speech.tts.fakes import (
    InterruptOnFirstEngine,
    RecordingEngine,
    SpeakingProbeEngine,
)

TTS_ROOT = Path(__file__).resolve().parents[4] / "speech" / "tts"


def _model() -> ModelInfo:
    return ModelInfo(
        provider_id="tts_local",
        model_id="local-tts",
        display_name="Local TTS",
        audio_output=True,
        local=True,
        source="test",
        license="test",
    )


def _request(text: str) -> SpeechRequest:
    return SpeechRequest(model=_model(), text=text)


@pytest.mark.asyncio
async def test_sentence_chunking_calls_engine_per_sentence() -> None:
    engine = RecordingEngine()
    provider = LocalTTSProvider(engine=engine, voice="anna")
    text = "Привет. Как дела? Отлично!"
    stream = await provider.synthesize(_request(text))
    expected = split_sentences(text)
    assert [call["text"] for call in engine.calls] == expected
    assert len(engine.calls) == 3
    assert stream.mime_type == "audio/wav"
    assert stream.data == "".join(expected).encode("utf-8")


@pytest.mark.asyncio
async def test_interrupt_stops_remaining_sentences() -> None:
    provider = LocalTTSProvider(engine=RecordingEngine(), voice="anna")
    engine = InterruptOnFirstEngine(provider)
    provider.engine = engine
    stream = await provider.synthesize(_request("Первое. Второе. Третье."))
    assert engine.texts == ["Первое."]
    assert stream.data == b"chunk"
    assert provider.is_speaking is False


@pytest.mark.asyncio
async def test_is_speaking_true_during_synthesize_false_after() -> None:
    probe = SpeakingProbeEngine(lambda: provider)
    provider = LocalTTSProvider(engine=probe, voice="anna")
    assert provider.is_speaking is False
    await provider.synthesize(_request("Одно предложение."))
    assert probe.seen == [True]
    assert provider.is_speaking is False


@pytest.mark.asyncio
async def test_preview_uses_the_same_engine_path() -> None:
    engine = RecordingEngine()
    provider = LocalTTSProvider(engine=engine, voice="anna", speed=1.25, volume=0.5)
    stream = await provider.preview("Проба. Ещё раз.")
    assert isinstance(stream, AudioStream)
    assert [call["text"] for call in engine.calls] == ["Проба.", "Еще раз."]
    assert engine.calls[0]["voice"] == "anna"
    assert engine.calls[0]["speed"] == 1.25
    assert engine.calls[0]["volume"] == 0.5


@pytest.mark.asyncio
async def test_synthesize_satisfies_protocol_and_forwards_voice() -> None:
    engine = RecordingEngine()
    provider = LocalTTSProvider(engine=engine, voice="milena")
    assert isinstance(provider, TextToSpeechProvider)
    await provider.synthesize(_request("Готово."))
    assert engine.calls[0]["voice"] == "milena"
    assert engine.calls[0]["speed"] == 1.0
    assert engine.calls[0]["volume"] == 1.0


@pytest.mark.asyncio
async def test_previous_interrupt_does_not_block_next_utterance() -> None:
    engine = RecordingEngine()
    provider = LocalTTSProvider(engine=engine, voice="anna")
    provider.interrupt()
    await provider.synthesize(_request("Снова. Говорю."))
    assert len(engine.calls) == 2


@pytest.mark.asyncio
async def test_normalize_yo_reaches_the_engine() -> None:
    engine = RecordingEngine()
    provider = LocalTTSProvider(engine=engine, voice="anna")
    await provider.preview("ёлка.")
    assert engine.calls[0]["text"] == "елка."


def test_core_tts_modules_do_not_hard_depend_on_piper() -> None:
    """LocalTTSProvider stays engine-agnostic; Piper is an optional inject."""
    import speech.tts as tts_pkg
    import speech.tts.normalize as normalize_mod
    import speech.tts.provider as provider_mod
    import speech.tts.sentences as sentences_mod

    for module in (tts_pkg, normalize_mod, provider_mod, sentences_mod):
        source = inspect.getsource(module)
        assert "piper" not in source.lower()
        assert "speech.tts.piper" not in getattr(module, "__dict__", {})
    piper_path = TTS_ROOT / "piper.py"
    assert piper_path.is_file()
    # Optional Piper glue may mention piper; core normalize/provider/sentences must not.
    allowed_piper_mentions = frozenset(
        {
            "piper.py",
            "local_factory.py",
            "download.py",
            "__main__.py",
        }
    )
    for path in TTS_ROOT.rglob("*.py"):
        if path.name in allowed_piper_mentions:
            continue
        assert "piper" not in path.read_text(encoding="utf-8").lower()


def test_package_does_not_invoke_macos_say(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("macOS say / subprocess must not be called")

    monkeypatch.setattr(subprocess, "run", _blocked)
    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "call", _blocked)
    engine = RecordingEngine()
    LocalTTSProvider(engine=engine, voice="anna")
    assert engine.calls == []
