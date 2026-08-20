"""Audio input, transport, and playback for Gemini Live sessions."""

from __future__ import annotations

import asyncio
import threading
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

    def bind(self, session: Any) -> None:
        """Bind fresh queues to one newly connected session."""
        self.session = session
        self.audio_in_queue = FreshAudioQueue(PLAYBACK_QUEUE_CHUNKS)
        self.out_queue = FreshAudioQueue(MIC_QUEUE_CHUNKS)

    def unbind(self) -> None:
        if self.out_queue is not None:
            self.dropped_microphone_chunks += self.out_queue.dropped_chunks
        if self.audio_in_queue is not None:
            self.dropped_playback_chunks += self.audio_in_queue.dropped_chunks
        self.session = None
        self.audio_in_queue = None
        self.out_queue = None

    async def send_realtime(self) -> None:
        if self.session is None or self.out_queue is None:
            raise RuntimeError("audio pipeline is not bound")
        while True:
            message = await self.out_queue.get()
            if not getattr(self.latency_trace, "active", False):
                self.latency_trace.start_turn()
                self.latency_trace.mark("user_input_activity_start")
                self.latency_trace.mark("provider_request_start")
            await self.session.send_realtime_input(media=message)

    async def listen(self) -> None:
        if self.out_queue is None:
            raise RuntimeError("audio pipeline is not bound")
        print("[SLON] 🎤 Mic started")
        import sounddevice as sd

        loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            with self.speaking_lock:
                slon_speaking = self.is_speaking()
            if not slon_speaking and not self.ui.muted:
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": indata.tobytes(), "mime_type": "audio/pcm"},
                )

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
                chunk = await self.audio_in_queue.get()
                self.latency_trace.mark("first_audio_output")
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()


__all__ = ["AudioPipeline", "FreshAudioQueue"]
