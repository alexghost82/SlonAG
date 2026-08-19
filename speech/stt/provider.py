"""Local SpeechToTextProvider with an injected engine.

Engines are wrapped behind ``STTEngine``. This module does not import
whisper implementations, read API keys, open a microphone, or touch the
network.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from typing import Protocol

from providers.contracts import AudioRequest, Transcript

PROVIDER_ID = "stt_local"
DEFAULT_LANGUAGE = "ru"

CancelledFlag = threading.Event | Callable[[], bool]


class STTEngine(Protocol):
    """Sync transcription backend. Optional kwargs are detected at call time."""

    def transcribe(self, audio: bytes, language: str) -> str: ...


def _supports_kwarg(func: Callable[..., object], name: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    parameters = signature.parameters
    if name in parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _flag_is_set(flag: CancelledFlag | None) -> bool:
    if flag is None:
        return False
    is_set = getattr(flag, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    if callable(flag):
        return bool(flag())
    return False


class LocalSTTProvider:
    """Local STT adapter. Echo-guard, cancel, and VAD skip the engine."""

    provider_id = PROVIDER_ID

    def __init__(
        self,
        engine: STTEngine,
        language: str = DEFAULT_LANGUAGE,
        is_assistant_speaking: Callable[[], bool] | None = None,
        *,
        on_partial: Callable[[str], None] | None = None,
        vad_detect: Callable[[bytes], bool] | None = None,
        cancelled: CancelledFlag | None = None,
    ) -> None:
        self._engine = engine
        self.language = language
        self.is_assistant_speaking = is_assistant_speaking
        self.on_partial = on_partial
        self.vad_detect = vad_detect
        self._external_cancelled = cancelled
        self.cancelled = (
            cancelled if isinstance(cancelled, threading.Event) else threading.Event()
        )

    def cancel(self) -> None:
        """Abort an in-flight or subsequent ``transcribe`` call."""
        self.cancelled.set()

    def _is_cancelled(self) -> bool:
        if self.cancelled.is_set():
            return True
        if self._external_cancelled is self.cancelled:
            return False
        return _flag_is_set(self._external_cancelled)

    def _should_skip_engine(self, audio: bytes) -> bool:
        speaking = self.is_assistant_speaking
        if speaking is not None and speaking():
            return True
        if self._is_cancelled():
            return True
        detect = self.vad_detect
        if detect is not None and not detect(audio):
            return True
        return False

    def _invoke_engine(self, audio: bytes) -> str:
        transcribe = self._engine.transcribe
        kwargs: dict[str, object] = {}
        if self.on_partial is not None and _supports_kwarg(transcribe, "on_partial"):
            kwargs["on_partial"] = self.on_partial
        if _supports_kwarg(transcribe, "cancelled"):
            kwargs["cancelled"] = self._is_cancelled
        if kwargs:
            return transcribe(audio, self.language, **kwargs)
        return transcribe(audio, self.language)

    async def transcribe(self, request: AudioRequest) -> Transcript:
        if self._should_skip_engine(request.audio):
            return Transcript(text="")
        text = await asyncio.to_thread(self._invoke_engine, request.audio)
        if self._is_cancelled() and not text:
            return Transcript(text="")
        return Transcript(text=text)
