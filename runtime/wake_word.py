"""Always-on local wake-word voice loop for text-based providers."""

from __future__ import annotations

import asyncio
import array
import logging
from pathlib import Path
import queue
import re
import threading
from collections.abc import Callable

from providers.contracts import AudioRequest, ModelInfo
from speech.stt.mic import pcm16_to_wav

logger = logging.getLogger(__name__)

WAKE_WORDS = ("slon", "слон")
WAKE_WINDOW_SECONDS = 2.0
COMMAND_MAX_SECONDS = 6.0
COMMAND_SILENCE_SECONDS = 0.8
FRAME_SECONDS = 0.08
SAMPLE_RATE = 16_000
SPEECH_RMS_THRESHOLD = 300


class OpenWakeWordDetector:
    """Optional adapter around a local openWakeWord model file."""

    def __init__(self, model: object, threshold: float = 0.5) -> None:
        self._model = model
        self._threshold = threshold

    @classmethod
    def from_model_path(cls, model_path: str | Path, threshold: float = 0.5) -> "OpenWakeWordDetector | None":
        path = Path(model_path)
        if not path.is_file():
            return None
        try:
            from openwakeword.model import Model

            return cls(Model(wakeword_models=[str(path)], vad_threshold=0.5), threshold)
        except Exception:
            logger.exception("openWakeWord model unavailable")
            return None

    def detect(self, pcm: bytes) -> bool:
        samples = array.array("h")
        samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
        if not samples:
            return False
        predictions = self._model.predict(samples)
        return any(float(score) >= self._threshold for score in predictions.values())


class WakeWordListener:
    """Detect ``Slon`` locally and forward the following command to the agent."""

    def __init__(
        self,
        *,
        mic: object,
        stt_provider: object,
        on_command: Callable[[str], None],
        on_log: Callable[[str], None],
        on_state: Callable[[str], None],
        detector: object | None = None,
        wake_model_path: str | Path | None = None,
    ) -> None:
        self._mic = mic
        self._stt_provider = stt_provider
        self._on_command = on_command
        self._on_log = on_log
        self._on_state = on_state
        self._detector = detector or (
            OpenWakeWordDetector.from_model_path(wake_model_path) if wake_model_path else None
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="slon-wake-word", daemon=True)
        self._thread.start()
        mode = "openWakeWord" if self._detector is not None else "ASR fallback"
        self._on_log(f"SYS: Wake word listener active ({mode}) — say 'Slon'.")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import sounddevice as sd

            audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=128)

            def callback(indata, *_args) -> None:
                if not self._stop.is_set():
                    try:
                        audio_queue.put_nowait(indata.tobytes())
                    except queue.Full:
                        audio_queue.get_nowait()
                        audio_queue.put_nowait(indata.tobytes())

            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=int(SAMPLE_RATE * FRAME_SECONDS),
                callback=callback,
            ):
                self._on_log("SYS: Wake word listener is listening.")
                while not self._stop.is_set():
                    if self._wait_for_wake_word(audio_queue):
                        self._on_log("SYS: Wake word detected — listening.")
                        self._on_state("LISTENING")
                        command = self._transcribe_command(audio_queue)
                        command = self._remove_wake_word(command).strip()
                        if command:
                            self._on_command(command)
        except Exception as exc:  # microphone and model errors must not kill the listener
            logger.exception("wake word listener failed")
            self._on_log(f"SYS: Wake word listener error — {type(exc).__name__}")

    def _wait_for_wake_word(self, audio_queue: queue.Queue[bytes]) -> bool:
        if self._detector is None:
            return self._contains_wake_word(self._transcribe_window(audio_queue, WAKE_WINDOW_SECONDS))
        while not self._stop.is_set():
            try:
                frame = audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if bool(self._detector.detect(frame)):  # type: ignore[attr-defined]
                    return True
            except Exception:
                logger.exception("wake word detector failed; falling back to ASR")
                self._detector = None
                return self._contains_wake_word(self._transcribe_window(audio_queue, WAKE_WINDOW_SECONDS))
        return False

    def _transcribe_window(self, audio_queue: queue.Queue[bytes], duration: float) -> str:
        chunks: list[bytes] = []
        for _ in range(round(duration / 0.05)):
            if self._stop.is_set():
                return ""
            try:
                chunks.append(audio_queue.get(timeout=0.2))
            except queue.Empty:
                continue
        audio = pcm16_to_wav(b"".join(chunks), sample_rate=SAMPLE_RATE, channels=1)
        model = ModelInfo(
            provider_id="stt_local",
            model_id="local-whisper",
            display_name="Local Whisper",
            audio_input=True,
            local=True,
        )
        transcript = asyncio.run(
            self._stt_provider.transcribe(AudioRequest(model=model, audio=audio))  # type: ignore[attr-defined]
        )
        return str(getattr(transcript, "text", "") or "")

    def _transcribe_command(self, audio_queue: queue.Queue[bytes]) -> str:
        """Collect one spoken command, ending shortly after its last speech frame."""
        chunks: list[bytes] = []
        saw_speech = False
        silent_frames = 0
        max_frames = round(COMMAND_MAX_SECONDS / FRAME_SECONDS)
        silence_frames = round(COMMAND_SILENCE_SECONDS / FRAME_SECONDS)
        for _ in range(max_frames):
            if self._stop.is_set():
                return ""
            try:
                frame = audio_queue.get(timeout=FRAME_SECONDS * 2)
            except queue.Empty:
                continue
            chunks.append(frame)
            if self._has_speech(frame):
                saw_speech = True
                silent_frames = 0
            elif saw_speech:
                silent_frames += 1
                if silent_frames >= silence_frames:
                    break
        if not saw_speech:
            return ""
        audio = pcm16_to_wav(b"".join(chunks), sample_rate=SAMPLE_RATE, channels=1)
        model = ModelInfo(
            provider_id="stt_local",
            model_id="faster-whisper",
            display_name="Local STT",
            audio_input=True,
            local=True,
        )
        transcript = asyncio.run(
            self._stt_provider.transcribe(AudioRequest(model=model, audio=audio))  # type: ignore[attr-defined]
        )
        return str(getattr(transcript, "text", "") or "")

    @staticmethod
    def _has_speech(pcm: bytes) -> bool:
        samples = array.array("h")
        samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
        if not samples:
            return False
        mean_square = sum(sample * sample for sample in samples) / len(samples)
        return mean_square**0.5 >= SPEECH_RMS_THRESHOLD

    @staticmethod
    def _contains_wake_word(text: str) -> bool:
        normalized = text.casefold()
        return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", normalized) for word in WAKE_WORDS)

    @staticmethod
    def _remove_wake_word(text: str) -> str:
        normalized = text.strip()
        lowered = normalized.lower()
        for word in WAKE_WORDS:
            index = lowered.find(word)
            if index >= 0:
                return normalized[index + len(word) :]
        return normalized


__all__ = ["OpenWakeWordDetector", "WakeWordListener"]
