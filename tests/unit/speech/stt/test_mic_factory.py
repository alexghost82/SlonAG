"""Unit tests for STT mic capture and local factory (no real microphone)."""

from __future__ import annotations

import array

import pytest

from speech.stt.engines import CallbackSTTEngine, EmptySTTEngine
from speech.stt.local_factory import try_build_local_stt
from speech.stt.mic import MicCapture, pcm16_to_wav
from speech.stt.provider import LocalSTTProvider
from providers.contracts import AudioRequest, ModelInfo


def test_pcm16_to_wav_has_riff_header() -> None:
    pcm = array.array("h", [0, 1000, -1000, 0]).tobytes()
    wav = pcm16_to_wav(pcm, sample_rate=16000, channels=1)
    assert wav[:4] == b"RIFF"
    assert b"WAVE" in wav[:16]


def test_mic_capture_uses_injected_recorder() -> None:
    frames_holder: list[int] = []

    def fake_rec(frames, samplerate, channels=1, dtype="int16"):
        frames_holder.append(frames)
        return array.array("h", [0] * frames)

    cap = MicCapture(recorder=fake_rec, sample_rate=16000, channels=1)
    result = cap.record(0.1)
    assert frames_holder == [1600]
    assert result.audio[:4] == b"RIFF"
    assert result.duration_s == 0.1


def test_mic_capture_rejects_non_positive_duration() -> None:
    with pytest.raises(ValueError):
        MicCapture(recorder=lambda *a, **k: array.array("h", [0])).record(0)


async def test_empty_engine_yields_blank_transcript() -> None:
    provider = LocalSTTProvider(EmptySTTEngine())
    model = ModelInfo(
        provider_id="stt_local",
        model_id="x",
        display_name="x",
        audio_input=True,
    )
    out = await provider.transcribe(AudioRequest(model=model, audio=b"RIFF"))
    assert out.text == ""


async def test_callback_engine_forwards_audio() -> None:
    seen: list[tuple[bytes, str]] = []

    def _fn(audio: bytes, language: str) -> str:
        seen.append((audio, language))
        return "привет"

    provider = LocalSTTProvider(CallbackSTTEngine(_fn), language="ru")
    model = ModelInfo(
        provider_id="stt_local",
        model_id="x",
        display_name="x",
        audio_input=True,
    )
    out = await provider.transcribe(AudioRequest(model=model, audio=b"wav"))
    assert out.text == "привет"
    assert seen == [(b"wav", "ru")]


def test_try_build_local_stt_without_requiring_mic() -> None:
    result = try_build_local_stt(prefer_whisper=False, require_mic=False)
    assert result.ready is True
    assert result.provider is not None
    assert result.asr_backend == "empty"
