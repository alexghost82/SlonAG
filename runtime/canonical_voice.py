"""Canonical voice pipeline: STT -> AgentLoop -> TTS -> playback.

Decoupled from Gemini Live.  Works with any provider that implements the
ChatProvider / ToolProvider contract (OpenAI, OpenRouter, Ollama, LM Studio,
llama.cpp, etc.).  Gemini Live stays as the optional realtime mode.

Audio fixture (E2E test)
------------------------
    audio_fixture -> FakeSTTProvider -> AgentLoop(mock) -> FakeTTSProvider -> bytes
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from runtime.events import RuntimeEventKind

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────
MIC_SAMPLE_RATE = 16_000
MIC_CHANNELS = 1
MIC_CHUNK_DURATION = 0.05  # 50 ms
TTS_SAMPLE_RATE = 24_000
TTS_CHANNEL = 1

# Queue capacity - discard oldest when full (stale audio)
MIC_QUEUE_CAP = 32
TTS_QUEUE_CAP = 64
TEXT_QUEUE_CAP = 8

# VAD silence timeout (seconds) - silence longer than this triggers STT
VAD_SILENCE_TIMEOUT = 0.6
# Reconnect back-off
RECONNECT_DELAY_S = 2.0
RECONNECT_MAX_DELAY_S = 30.0
RECONNECT_FAILURES_BEFORE_ABORT = 50

# ── config ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class VoiceConfig:
    """Voice pipeline configuration.

    Parameters are provider-neutral; implementations wire the actual
    engine (faster-whisper, Whisper, Coqui, Piper, ...) at runtime.
    """

    language: str = "ru"
    stt_engine: str = "faster_whisper"
    tts_engine: str = "piper"
    tts_voice: str = ""
    tts_speed: float = 1.0
    tts_volume: float = 1.0

    mic_device: int | str | None = None
    speaker_device: int | str | None = None

    muted: bool = False
    barge_in: bool = True

    # Optional VAD callable: lambda audio: bool (speech activity in chunk)
    vad: Callable[[bytes], bool] | None = None


# ── bounded queues with stale-discard ────────────────────────────────────
class FreshAudioQueue(asyncio.Queue):
    """Bounded queue that drops the oldest chunk when full."""

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self.dropped_chunks: int = 0

    def put_nowait(self, item: bytes) -> None:
        while self.full():
            try:
                self.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.dropped_chunks += 1
        super().put_nowait(item)


class FreshTextQueue(asyncio.Queue):
    """Bounded text queue - drops oldest on overflow."""

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self.dropped_chunks: int = 0

    def put_nowait(self, item: str) -> None:
        while self.full():
            try:
                self.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.dropped_chunks += 1
        super().put_nowait(item)


# ── playback generation guard ───────────────────────────────────────────
class PlaybackGeneration:
    """Monotonically increasing generation for barge-in / stale discard."""

    def __init__(self) -> None:
        self._value: int = 0
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def bump(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


# ── STT / TTS adapters ─────────────────────────────────────────────────
class STTAdapter:
    """Adapter wrapping an STT provider for the voice pipeline."""

    def __init__(
        self,
        provider: Any,  # must implement SpeechToTextProvider
        language: str,
        vad: Callable[[bytes], bool] | None = None,
        cancelled: threading.Event | None = None,
        speaking_callback: Callable[[], bool] | None = None,
    ) -> None:
        self.provider = provider
        self.language = language
        self.vad = vad
        self._cancelled = cancelled or threading.Event()
        self._speaking = speaking_callback

    def cancel(self) -> None:
        self._cancelled.set()

    def _should_skip(self, audio: bytes) -> bool:
        if self._cancelled.is_set():
            return True
        if self._speaking is not None and self._speaking():
            return True
        if self.vad is not None and not self.vad(audio):
            return True
        return False

    async def transcribe(self, audio: bytes) -> str:
        """Return transcribed text or empty string."""
        if self._should_skip(audio):
            return ""
        try:
            from providers.contracts import AudioRequest, ModelInfo, Transcript
            result = await self.provider.transcribe(
                AudioRequest(
                    model=ModelInfo(
                        provider_id=getattr(self.provider, "provider_id", "stt"),
                        model_id="",
                        display_name="STT",
                        audio_input=True,
                    ),
                    audio=audio,
                )
            )
            return getattr(result, "text", "") or ""
        except Exception:
            logger.exception("STT error")
            return ""


class TTSAdapter:
    """Adapter wrapping a TTS provider for the voice pipeline."""

    def __init__(
        self,
        provider: Any,  # must implement TextToSpeechProvider
        voice: str,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        self.provider = provider
        self.voice = voice
        self.speed = speed
        self.volume = volume
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def interrupt(self) -> None:
        self._speaking = False

    async def synthesize(self, text: str) -> bytes:
        """Return audio bytes."""
        self._speaking = True
        try:
            from providers.contracts import ModelInfo, SpeechRequest
            result = await self.provider.synthesize(
                SpeechRequest(
                    model=ModelInfo(
                        provider_id=getattr(self.provider, "provider_id", "tts"),
                        model_id="",
                        display_name="TTS",
                        audio_output=True,
                    ),
                    text=text,
                )
            )
            return getattr(result, "data", b"") or b""
        except Exception:
            logger.exception("TTS error")
            return b""
        finally:
            self._speaking = False


# ── canonical voice bridge ──────────────────────────────────────────────
class VoiceBridge:
    """Canonical voice pipeline: mic -> STT -> AgentLoop -> TTS -> playback.

    Works with any ChatProvider that supports the agent-loop contract.
    Manages bounded queues, barge-in, stale audio discard, and reconnect.

    Parameters
    ----------
    config: VoiceConfig
    ui: SlonUI - must have muted, write_log, and optionally is_speaking, speak
    agent_loop_factory: Callable[[ModelInfo, provider, executor], AgentLoop]
    model_info: ModelInfo for the text provider
    set_speaking: Callback(bool) for UI speaking indicator
    """

    def __init__(
        self,
        *,
        config: VoiceConfig,
        ui: Any,
        agent_loop_factory: Callable[
            [Any, Any, Any], Any
        ],
        model_info: Any,  # ModelInfo
        set_speaking: Callable[[bool], None],
    ) -> None:
        self.config = config
        self.ui = ui
        self.agent_loop_factory = agent_loop_factory
        self.model_info = model_info
        self.set_speaking = set_speaking
        self._running = False
        self._cancelled = threading.Event()
        self._generation = PlaybackGeneration()
        self._stt_adapter: STTAdapter | None = None
        self._tts_adapter: TTSAdapter | None = None
        self._agent_loop: Any = None

    def cancel(self) -> None:
        """Request the pipeline to stop."""
        self._cancelled.set()
        if self._stt_adapter is not None:
            self._stt_adapter.cancel()

    def interrupt_tts(self) -> None:
        """Barge-in: stop TTS and invalidate stale output."""
        if self._tts_adapter is not None:
            self._tts_adapter.interrupt()
        self._generation.bump()
        self.set_speaking(False)

    async def _build_stt(self) -> STTAdapter:
        """Build STT adapter from model_info provider."""
        from providers.contracts import ChatProvider

        # Try to build a dedicated STT provider
        # Check for stt_engine in config and resolve via the provider system
        provider_id = self.model_info.provider_id if hasattr(self.model_info, "provider_id") else "local"

        # Try to resolve STT from the provider router
        try:
            from providers.router import Router
            router = Router(provider_id=provider_id, network_mode="hybrid")
            provider = router._resolve(provider_id)
        except Exception:
            logger.exception("Could not resolve provider for STT, using fallback")
            # Fallback: create a minimal STT-compatible wrapper
            provider = None

        return STTAdapter(
            provider=provider,
            language=self.config.language,
            vad=self.config.vad,
            cancelled=self._cancelled,
            speaking_callback=self.ui.is_speaking
            if hasattr(self.ui, "is_speaking") and callable(self.ui.is_speaking)
            else None,
        )

    async def _build_tts(self) -> TTSAdapter:
        """Build TTS adapter from model_info provider."""
        provider_id = self.model_info.provider_id if hasattr(self.model_info, "provider_id") else "local"
        try:
            from providers.router import Router
            router = Router(provider_id=provider_id, network_mode="hybrid")
            provider = router._resolve(provider_id)
        except Exception:
            logger.exception("Could not resolve provider for TTS, using fallback")
            provider = None

        return TTSAdapter(
            provider=provider,
            voice=self.config.tts_voice,
            speed=self.config.tts_speed,
            volume=self.config.tts_volume,
        )

    async def _build_agent_loop(self) -> None:
        """Build AgentLoop from the model_info's provider."""
        try:
            from mark.tools.builtin import build_builtin_registry
            from mark.tools.executor import ToolExecutor
            from mark.safety.policy import SafetyPolicy
            from agent.runtime import AgentLoop

            registry = build_builtin_registry()
            safety = SafetyPolicy()
            executor = ToolExecutor(registry, safety)

            from providers.router import Router
            provider_id = self.model_info.provider_id if hasattr(self.model_info, "provider_id") else "local"
            router = Router(provider_id=provider_id, network_mode="hybrid")
            provider = router._resolve(provider_id)

            self._agent_loop = self.agent_loop_factory(
                self.model_info, provider, executor
            )
        except Exception:
            logger.exception("Failed to build AgentLoop")
            raise

    async def _mic_capture(self, queue: FreshAudioQueue) -> None:
        """Read microphone and push PCM16 chunks to queue."""
        import sounddevice as sd

        device = self.config.mic_device
        try:
            stream = sd.InputStream(
                samplerate=MIC_SAMPLE_RATE,
                channels=MIC_CHANNELS,
                dtype="int16",
                blocksize=int(MIC_SAMPLE_RATE * MIC_CHUNK_DURATION),
                callback=lambda indata, *_: (
                    queue.put_nowait(indata.tobytes())
                    if not getattr(self.ui, "muted", False)
                    else None
                ),
                device=device,
            )
        except Exception:
            logger.exception("microphone open failed")
            # Try without explicit device
            try:
                stream = sd.InputStream(
                    samplerate=MIC_SAMPLE_RATE,
                    channels=MIC_CHANNELS,
                    dtype="int16",
                    blocksize=int(MIC_SAMPLE_RATE * MIC_CHUNK_DURATION),
                    callback=lambda indata, *_: (
                        queue.put_nowait(indata.tobytes())
                        if not getattr(self.ui, "muted", False)
                        else None
                    ),
                )
            except Exception:
                logger.exception("microphone open failed (no device fallback)")
                return

        stream.start()
        logger.info("voice: mic started at %d Hz", MIC_SAMPLE_RATE)
        try:
            while not self._cancelled.is_set():
                await asyncio.sleep(MIC_CHUNK_DURATION)
        finally:
            stream.stop()
            stream.close()
            logger.info("voice: mic stopped")

    async def _stt_loop(
        self,
        mic_queue: FreshAudioQueue,
        text_queue: FreshTextQueue,
    ) -> None:
        """Collect mic chunks, VAD-gated speech accumulation, STT."""
        assert self._stt_adapter is not None
        buffer: list[bytes] = []
        silence_count = 0
        silence_threshold = int(
            VAD_SILENCE_TIMEOUT / MIC_CHUNK_DURATION
        )

        while not self._cancelled.is_set():
            try:
                chunk = await asyncio.wait_for(mic_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            buffer.append(chunk)
            silence_count += 1

            if silence_count >= silence_threshold and buffer:
                payload = b"".join(buffer)
                buffer.clear()
                silence_count = 0
                text = await self._stt_adapter.transcribe(payload)
                if text:
                    logger.info("voice: STT -> '%s'", text[:80])
                    text_queue.put_nowait(text)

    async def _agent_turn(
        self,
        text: str,
        history: list[dict],
    ) -> str | None:
        """Run one AgentLoop turn, return assistant text."""
        assert self._agent_loop is not None
        logger.info("voice: agent turn: %s", text[:80)
        try:
            result = await self._agent_loop.run(
                user_goal=text,
                history=history,
                on_message=lambda msg: (
                    self.ui.write_log(str(msg))
                    if hasattr(self.ui, "write_log")
                    else None
                ),
            )
            if result is None:
                return None

            # Normalize response
            if hasattr(result, "text"):
                return result.text
            if hasattr(result, "content"):
                return result.content
            return str(result)
        except Exception:
            logger.exception("AgentLoop error")
            return None

    async def _tts_playback_task(
        self,
        tts_queue: asyncio.Queue[str],
        mic_queue: FreshAudioQueue,
    ) -> None:
        """Synthesize and play TTS output with barge-in guard."""
        assert self._tts_adapter is not None

        while not self._cancelled.is_set():
            try:
                text = await asyncio.wait_for(tts_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Barge-in / stale check
            if self._tts_adapter.interrupted if hasattr(self._tts_adapter, 'interrupted') else False:
                self._tts_adapter.interrupt()
                self.set_speaking(False)
                continue

            if not text or not text.strip():
                continue

            logger.info("voice: TTS: %s", text[:100])
            self.set_speaking(True)
            self._emit_event(RuntimeEventKind.SPEAKING)

            try:
                audio_data = await self._tts_adapter.synthesize(text)
                if self._cancelled.is_set():
                    break
                if audio_data:
                    await self._play_audio(audio_data)
            except Exception:
                logger.exception("TTS+playback error")
            finally:
                if not self._cancelled.is_set():
                    self.set_speaking(False)
                    self._emit_event(RuntimeEventKind.LISTENING)

    async def _play_audio(self, audio_data: bytes) -> None:
        """Play audio data through sounddevice."""
        import sounddevice as sd

        if not audio_data:
            return

        # Convert WAV or raw to int16 if needed
        try:
            stream = sd.RawOutputStream(
                samplerate=TTS_SAMPLE_RATE,
                channels=TTS_CHANNEL,
                dtype="int16",
            )
            stream.start()
            try:
                if len(audio_data) % 2 != 0:
                    audio_data += b"\x00"
                stream.write(audio_data)
            finally:
                stream.stop()
                stream.close()
        except Exception:
            logger.exception("playback error")

    def _emit_event(self, kind: RuntimeEventKind, **kw: Any) -> None:
        """Emit runtime event through the UI."""
        try:
            emit = getattr(self.ui, "emit_event", None)
            if emit:
                emit(kind, **kw)
        except Exception:
            pass

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the canonical voice pipeline until cancelled or unrecoverable error."""
        if self._running:
            return
        self._running = True

        # Build components
        self._stt_adapter = await self._build_stt()
        self._tts_adapter = await self._build_tts()
        await self._build_agent_loop()

        mic_queue = FreshAudioQueue(MIC_QUEUE_CAP)
        text_queue = FreshTextQueue(TEXT_QUEUE_CAP)
        tts_queue: asyncio.Queue[str] = asyncio.Queue()

        reconnect_failures = 0

        while not self._cancelled.is_set() and reconnect_failures < RECONNECT_FAILURES_BEFORE_ABORT:
            try:
                tasks = [
                    asyncio.create_task(self._mic_capture(mic_queue)),
                    asyncio.create_task(self._stt_loop(mic_queue, text_queue)),
                    asyncio.create_task(
                        self._agent_consumer_loop(text_queue, tts_queue)
                    ),
                    asyncio.create_task(
                        self._tts_playback_task(tts_queue, mic_queue)
                    ),
                ]
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("pipeline error, reconnecting in %.1fs", RECONNECT_DELAY_S)
                reconnect_failures += 1
                self.set_speaking(False)
                await asyncio.sleep(RECONNECT_DELAY_S)

        self._running = False
        logger.info("voice: pipeline stopped")

    async def _agent_consumer_loop(
        self,
        text_queue: FreshTextQueue,
        tts_queue: asyncio.Queue[str],
    ) -> None:
        """Consume STT text, run AgentLoop, send response to TTS queue."""
        assert self._agent_loop is not None
        history: list[dict[str, str]] = []

        while not self._cancelled.is_set():
            try:
                text = await asyncio.wait_for(text_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            response = await self._agent_turn(text, history)
            if response is not None and response.strip():
                history.append({"role": "assistant", "content": response})
                tts_queue.put_nowait(response)


__all__ = [
    "VoiceConfig",
    "VoiceBridge",
    "FreshAudioQueue",
    "FreshTextQueue",
    "PlaybackGeneration",
    "STTAdapter",
    "TTSAdapter",
]
