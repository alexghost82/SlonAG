"""Audio input, transport, and playback for Gemini Live sessions."""

from __future__ import annotations

import asyncio
import threading
from enum import StrEnum
from collections.abc import Callable
from typing import Any

SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK_SIZE = 1024
MIC_QUEUE_CHUNKS = 10
# Gemini can deliver generated audio faster than the device consumes it. Keep
# enough bounded burst capacity for coherent speech; reconnect still discards it.
PLAYBACK_QUEUE_CHUNKS = 256


class EchoSuppressionMode(StrEnum):
    """Document the active full-duplex echo/interruption policy."""

    SERVER_ACTIVITY_DETECTION = "server_activity_detection"


class FreshAudioQueue(asyncio.Queue):
    """Bounded queue that discards the oldest chunk instead of stale buffering."""

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self.dropped_chunks = 0

    def put_nowait(self, item: Any) -> None:
        if self.full():
            try:
                self.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                self.dropped_chunks += 1
        super().put_nowait(item)


class AudioPipeline:
    """Own audio queues and streams for one connected Live session."""

    def __init__(
        self,
        *,
        ui: Any,
        set_speaking: Callable[[bool], None],
        latency_trace: Any,
        speaking_lock: threading.Lock,
        is_speaking: Callable[[], bool],
    ) -> None:
        self.ui = ui
        self.set_speaking = set_speaking
        self.latency_trace = latency_trace
        self.speaking_lock = speaking_lock
        self.is_speaking = is_speaking
        self.session: Any = None
        self.audio_in_queue: FreshAudioQueue | None = None
        self.out_queue: FreshAudioQueue | None = None
        self.dropped_microphone_chunks = 0
        self.dropped_playback_chunks = 0
        self.playback_generation = 0
        self.echo_suppression_mode = EchoSuppressionMode.SERVER_ACTIVITY_DETECTION
        self._ingress_lock = threading.Lock()
        self._pending_microphone: dict[str, object] | None = None
        self._ingress_scheduled = False

    def bind(self, session: Any) -> None:
        """Bind fresh queues to one newly connected session."""
        self.session = session
        self.audio_in_queue = FreshAudioQueue(PLAYBACK_QUEUE_CHUNKS)
        self.out_queue = FreshAudioQueue(MIC_QUEUE_CHUNKS)
        self.playback_generation += 1

    def unbind(self) -> None:
        if self.out_queue is not None:
            self.dropped_microphone_chunks += self.out_queue.dropped_chunks
        if self.audio_in_queue is not None:
            self.dropped_playback_chunks += self.audio_in_queue.dropped_chunks
        self.session = None
        self.audio_in_queue = None
        self.out_queue = None
        self.playback_generation += 1

    def enqueue_playback(self, data: bytes) -> None:
        """Queue provider audio for the currently valid playback generation."""
        if self.audio_in_queue is None:
            raise RuntimeError("audio pipeline is not bound")
        self.audio_in_queue.put_nowait((self.playback_generation, data))

    def interrupt_playback(self) -> int:
        """Invalidate and discard pending audio from the interrupted response."""
        self.playback_generation += 1
        invalidated = 0
        if self.audio_in_queue is not None:
            while True:
                try:
                    self.audio_in_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                invalidated += 1
        self.set_speaking(False)
        return invalidated

    async def send_realtime(self) -> None:
        if self.session is None or self.out_queue is None:
            raise RuntimeError("audio pipeline is not bound")
        while True:
            message = await self.out_queue.get()
            if not getattr(self.latency_trace, "active", False):
                self.latency_trace.start_turn()
                self.latency_trace.mark("user_input_activity_start")
                self.latency_trace.mark("provider_request_start")
            await asyncio.wait_for(
                self.session.send_realtime_input(media=message), timeout=30.0
            )

    async def listen(self) -> None:
        if self.out_queue is None:
            raise RuntimeError("audio pipeline is not bound")
        print("[SLON] 🎤 Mic started")
        import sounddevice as sd

        loop = asyncio.get_running_loop()

        def drain_pending() -> None:
            with self._ingress_lock:
                message = self._pending_microphone
                self._pending_microphone = None
                self._ingress_scheduled = False
            if message is not None and self.out_queue is not None:
                self.out_queue.put_nowait(message)

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            # Gemini's server-side activity detection needs microphone audio in
            # order to signal an interruption. Muting remains the only local
            # capture gate; playback generations prevent stale assistant audio.
            if not self.ui.muted:
                message = {"data": indata.tobytes(), "mime_type": "audio/pcm"}
                with self._ingress_lock:
                    self._pending_microphone = message
                    if self._ingress_scheduled:
                        return
                    self._ingress_scheduled = True
                loop.call_soon_threadsafe(drain_pending)

        with sd.InputStream(
            samplerate=SEND_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
            callback=callback,
        ):
            print("[SLON] 🎤 Mic stream open")
            while True:
                await asyncio.sleep(0.1)

    async def play(self) -> None:
        if self.audio_in_queue is None:
            raise RuntimeError("audio pipeline is not bound")
        print("[SLON] 🔊 Play started")
        import sounddevice as sd

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                generation, chunk = await self.audio_in_queue.get()
                if generation != self.playback_generation:
                    continue
                self.latency_trace.mark("first_audio_output")
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()


__all__ = ["AudioPipeline", "EchoSuppressionMode", "FreshAudioQueue"]
