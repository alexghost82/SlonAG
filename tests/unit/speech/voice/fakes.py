"""Voice pipeline test fixtures and fakes."""

from __future__ import annotations

from collections.abc import Callable

from providers.contracts import AudioRequest, ModelInfo, SpeechRequest


class FakeAudioRequest:
    """Minimal AudioRequest."""

    def __init__(self, audio: bytes = b"fake") -> None:
        self._inner = AudioRequest(
            model=ModelInfo(
                provider_id="stt_local",
                model_id="fake",
                display_name="fake",
                audio_input=True,
            ),
            audio=audio,
        )

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class FakeSpeechRequest:
    """Minimal SpeechRequest."""

    def __init__(self, text: str = "test") -> None:
        self._inner = SpeechRequest(
            model=ModelInfo(
                provider_id="tts_local",
                model_id="fake",
                display_name="fake",
                audio_output=True,
            ),
            text=text,
        )

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class FakeSTTProvider:
    """STT provider that returns canned text."""

    provider_id = "stt_local"

    def __init__(self, text: str = "привет") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, request: AudioRequest) -> object:
        self.calls.append((request.audio, ""))
        from providers.contracts import Transcript
        return Transcript(text=self.text)


class FakeTTSProvider:
    """TTS provider that returns canned WAV bytes."""

    provider_id = "tts_local"

    def __init__(self, audio: bytes = b"RIFFfakeWAV") -> None:
        self.audio = audio
        self.calls: list[str] = []

    async def synthesize(self, request: SpeechRequest) -> object:
        self.calls.append(request.text)
        from providers.contracts import AudioStream
        return AudioStream(data=self.audio, mime_type="audio/wav")


class ExplodingTTSProvider:
    """TTS provider that raises on synthesize."""

    provider_id = "tts_local"

    async def synthesize(self, request: SpeechRequest) -> object:
        raise AssertionError("TTS provider must not be called")


class FakeUI:
    """Mock UI for VoiceBridge tests."""

    def __init__(self) -> None:
        self.speaking: bool = False
        self.log_lines: list[str] = []
        self.events: list[tuple[str, dict]] = []

    @property
    def muted(self) -> bool:
        return False

    def is_speaking(self) -> bool:
        return self.speaking

    def write_log(self, msg: str) -> None:
        self.log_lines.append(str(msg))

    def emit_event(self, kind: str, **kw: object) -> None:
        self.events.append((kind, kw))

    def set_speaking(self, value: bool) -> None:
        self.speaking = value
