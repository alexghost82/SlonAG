"""Local TextToSpeechProvider with sentence streaming and barge-in.

The synthesizer is injected. This module does not download voices and
does not call macOS ``say``.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from providers.contracts import AudioStream, SpeechRequest

from speech.tts.normalize import normalize_tts_text
from speech.tts.sentences import split_sentences

AUDIO_MIME_TYPE = "audio/wav"


class SpeechSynthesizer(Protocol):
    """In-process TTS engine. Implementations must not hit the network."""

    def synthesize(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        volume: float,
    ) -> bytes: ...


class LocalTTSProvider:
    """Sentence-streaming local TTS adapter with interrupt/barge-in."""

    provider_id = "tts_local"

    def __init__(
        self,
        engine: SpeechSynthesizer,
        voice: str,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        if engine is None:
            raise TypeError("engine is required")
        if not isinstance(voice, str) or not voice.strip():
            raise TypeError("voice must be a non-empty string")
        self.engine = engine
        self.voice = voice
        self.speed = speed
        self.volume = volume
        self._speaking = False
        self._interrupted = False

    @property
    def is_speaking(self) -> bool:
        """True while ``synthesize`` / ``preview`` is producing audio."""
        return self._speaking

    def interrupt(self) -> None:
        """Stop remaining sentences of the current utterance (barge-in)."""
        self._interrupted = True

    async def synthesize(self, request: SpeechRequest) -> AudioStream:
        return await self._synthesize_text(request.text)

    async def preview(self, text: str) -> AudioStream:
        """Speak ``text`` through the same normalize → chunk → engine path."""
        return await self._synthesize_text(text)

    async def _synthesize_text(self, text: str) -> AudioStream:
        self._interrupted = False
        self._speaking = True
        chunks: list[bytes] = []
        try:
            normalized = normalize_tts_text(text)
            for sentence in split_sentences(normalized):
                if self._interrupted:
                    break
                chunks.append(
                    self.engine.synthesize(
                        sentence,
                        voice=self.voice,
                        speed=self.speed,
                        volume=self.volume,
                    )
                )
                await asyncio.sleep(0)
            return AudioStream(data=b"".join(chunks), mime_type=AUDIO_MIME_TYPE)
        finally:
            self._speaking = False
