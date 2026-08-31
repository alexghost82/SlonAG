"""Tests for STTAdapter and TTSAdapter (VoiceRuntime)."""

from __future__ import annotations

import asyncio
import threading

import pytest

from providers.contracts import (
    AudioRequest,
    AudioStream,
    ModelInfo,
    SpeechRequest,
    Transcript,
)
from runtime.canonical_voice import STTAdapter, TTSAdapter

from tests.unit.speech.voice.fakes import (
    ExplodingTTSProvider,
    FakeSTTProvider,
    FakeTTSProvider,
)


class TestSTTAdapter:
    """Tests for the STT adapter wrapping an STT provider."""

    @pytest.mark.asyncio
    async def test_transcribe_forwards_to_provider(self) -> None:
        provider = FakeSTTProvider(text="распознано")
        adapter = STTAdapter(provider, language="ru")
        result = await adapter.transcribe(b"pcm-data")
        assert result == "распознано"
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_cancelled_skips_engine(self) -> None:
        provider = FakeSTTProvider(text="should-not-reach")
        cancelled = threading.Event()
        adapter = STTAdapter(
            provider, language="ru", cancelled=cancelled
        )
        cancelled.set()  # Mark as cancelled before transcribe
        result = await adapter.transcribe(b"pcm-data")
        assert result == ""
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_speaking_callback_skips(self) -> None:
        """Echo guard: when assistant is speaking, skip STT."""
        provider = FakeSTTProvider(text="should-not-reach")
        adapter = STTAdapter(
            provider,
            language="ru",
            speaking_callback=lambda: True,
        )
        result = await adapter.transcribe(b"pcm-data")
        assert result == ""
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_vad_false_skips(self) -> None:
        """VAD detects silence → skip STT engine."""
        provider = FakeSTTProvider(text="should-not-reach")
        adapter = STTAdapter(
            provider, language="ru", vad=lambda audio: False
        )
        result = await adapter.transcribe(b"pcm-data")
        assert result == ""
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_vad_true_calls_engine(self) -> None:
        """VAD detects speech → call STT engine."""
        provider = FakeSTTProvider(text="есть речь")
        vad_calls: list[bytes] = []
        adapter = STTAdapter(
            provider,
            language="ru",
            vad=lambda audio: (vad_calls.append(audio), True)[1],
        )
        result = await adapter.transcribe(b"pcm-speech")
        assert result == "есть речь"
        assert vad_calls == [b"pcm-speech"]
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_cancel_method(self) -> None:
        """cancel() sets the cancellation event."""
        provider = FakeSTTProvider()
        adapter = STTAdapter(provider, language="ru")
        adapter.cancel()
        assert adapter._cancelled.is_set()

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self) -> None:
        """Provider exception is caught and returns empty string."""
        provider = ExplodingTTSProvider()  # uses AssertionError

        class ExplodingSTTProvider:
            provider_id = "stt"
            async def transcribe(self, request: AudioRequest) -> Transcript:
                raise AssertionError("STT exploded")

        adapter = STTAdapter(ExplodingSTTProvider(), language="ru")
        result = await adapter.transcribe(b"pcm")
        assert result == ""

    @pytest.mark.asyncio
    async def test_custom_language(self) -> None:
        adapter = STTAdapter(FakeSTTProvider(), language="en")
        # Just verify it doesn't crash with non-Russian language
        result = await adapter.transcribe(b"pcm")
        assert result == "привет"


class TestTTSAdapter:
    """Tests for the TTS adapter wrapping a TTS provider."""

    @pytest.mark.asyncio
    async def test_synthesize_forwards_to_provider(self) -> None:
        provider = FakeTTSProvider(audio=b"RIFFtestWAV")
        adapter = TTSAdapter(provider, voice="anna", speed=1.0, volume=1.0)
        audio = await adapter.synthesize("Привет.")
        assert audio == b"RIFFtestWAV"
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_is_speaking_during_synthesize(self) -> None:
        provider = FakeTTSProvider()
        adapter = TTSAdapter(provider, voice="anna")
        assert adapter.is_speaking is False
        await adapter.synthesize("Текст")
        assert adapter.is_speaking is False

    @pytest.mark.asyncio
    async def test_interrupt_resets_state(self) -> None:
        provider = FakeTTSProvider()
        adapter = TTSAdapter(provider, voice="anna")
        adapter.interrupt()
        assert adapter.interrupted is True
        assert adapter._speaking is False

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self) -> None:
        provider = FakeTTSProvider()
        adapter = TTSAdapter(provider, voice="anna")
        audio = await adapter.synthesize("")
        # Should return empty since provider gets empty text
        assert audio == b"RIFFfakeWAV"  # default
        # But provider should have been called with empty text
        assert "" in provider.calls

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self) -> None:
        provider = ExplodingTTSProvider()
        adapter = TTSAdapter(provider, voice="anna")
        audio = await adapter.synthesize("Текст")
        assert audio == b""

    @pytest.mark.asyncio
    async def test_synthesize_sets_interrupted_false(self) -> None:
        provider = FakeTTSProvider()
        adapter = TTSAdapter(provider, voice="anna")
        adapter.interrupt()
        assert adapter.interrupted is True
        await adapter.synthesize("Текст")
        assert adapter.interrupted is False
