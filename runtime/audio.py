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
        self.audio_in_queue: asyncio.Queue[bytes] | None = None
        self.out_queue: asyncio.Queue[dict[str, object]] | None = None

    def bind(self, session: Any) -> None:
        """Bind fresh queues to one newly connected session."""
        self.session = session
        self.audio_in_queue = asyncio.Queue()
        self.out_queue = asyncio.Queue(maxsize=10)

    def unbind(self) -> None:
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


__all__ = ["AudioPipeline"]
