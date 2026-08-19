"""Microphone capture for local STT (sounddevice). No network; no transcription."""

from __future__ import annotations

import io
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_CHANNELS = 1
DEFAULT_DTYPE = "int16"


@dataclass(frozen=True)
class MicCaptureResult:
    """PCM WAV bytes plus capture metadata."""

    audio: bytes
    sample_rate: int
    channels: int
    duration_s: float


class MicCaptureError(RuntimeError):
    """Microphone unavailable or capture failed."""


def _default_sounddevice() -> Any:
    import sounddevice as sd

    return sd


def pcm16_to_wav(pcm: bytes, *, sample_rate: int, channels: int) -> bytes:
    """Wrap raw little-endian PCM16 in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class MicCapture:
    """Record a fixed-duration clip from the default input device."""

    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        sounddevice_module: Any | None = None,
        recorder: Callable[..., Any] | None = None,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")
        self.sample_rate = sample_rate
        self.channels = channels
        self._sd = sounddevice_module
        self._recorder = recorder

    def _sd_mod(self) -> Any:
        if self._sd is not None:
            return self._sd
        try:
            self._sd = _default_sounddevice()
        except Exception as exc:  # noqa: BLE001
            raise MicCaptureError(f"sounddevice unavailable: {exc}") from exc
        return self._sd

    def record(self, duration_s: float = 3.0) -> MicCaptureResult:
        """Block and record ``duration_s`` seconds of mono/stereo PCM16 WAV."""
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        frames = int(self.sample_rate * duration_s)
        try:
            if self._recorder is not None:
                data = self._recorder(
                    frames,
                    self.sample_rate,
                    channels=self.channels,
                    dtype=DEFAULT_DTYPE,
                )
            else:
                sd = self._sd_mod()
                data = sd.rec(
                    frames,
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=DEFAULT_DTYPE,
                )
                sd.wait()
            pcm = bytes(memoryview(data).cast("B")) if not isinstance(data, (bytes, bytearray)) else bytes(data)
            # numpy int16 array → raw bytes
            tobytes = getattr(data, "tobytes", None)
            if callable(tobytes):
                pcm = tobytes()
        except MicCaptureError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MicCaptureError(f"microphone capture failed: {exc}") from exc

        wav = pcm16_to_wav(pcm, sample_rate=self.sample_rate, channels=self.channels)
        return MicCaptureResult(
            audio=wav,
            sample_rate=self.sample_rate,
            channels=self.channels,
            duration_s=float(duration_s),
        )


__all__ = [
    "DEFAULT_CHANNELS",
    "DEFAULT_SAMPLE_RATE",
    "MicCapture",
    "MicCaptureError",
    "MicCaptureResult",
    "pcm16_to_wav",
]
