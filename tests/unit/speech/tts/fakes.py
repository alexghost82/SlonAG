"""In-process TTS engine stand-ins. No subprocess, network, or ``say``."""

from __future__ import annotations

from collections.abc import Callable

from speech.tts.provider import LocalTTSProvider


class RecordingEngine:
    """Records each sentence call and returns deterministic audio bytes."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def synthesize(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        volume: float,
    ) -> bytes:
        self.calls.append(
            {"text": text, "voice": voice, "speed": speed, "volume": volume}
        )
        return text.encode("utf-8")


class InterruptOnFirstEngine:
    """Calls ``provider.interrupt()`` after the first sentence."""

    def __init__(self, provider: LocalTTSProvider) -> None:
        self.provider = provider
        self.texts: list[str] = []

    def synthesize(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        volume: float,
    ) -> bytes:
        self.texts.append(text)
        self.provider.interrupt()
        return b"chunk"


class SpeakingProbeEngine:
    """Records ``is_speaking`` as seen from inside the engine."""

    def __init__(self, provider_getter: Callable[[], LocalTTSProvider]) -> None:
        self._provider_getter = provider_getter
        self.seen: list[bool] = []

    def synthesize(
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        volume: float,
    ) -> bytes:
        self.seen.append(self._provider_getter().is_speaking)
        return b"x"
