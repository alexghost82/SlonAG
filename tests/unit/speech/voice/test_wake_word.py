"""Tests for streaming wake-word detection and command endpointing."""

from __future__ import annotations

import queue
from types import SimpleNamespace

from runtime.wake_word import WakeWordListener


class _Detector:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.frames: list[bytes] = []

    def detect(self, frame: bytes) -> bool:
        self.frames.append(frame)
        return self.result


def _listener(detector: object | None = None) -> WakeWordListener:
    return WakeWordListener(
        mic=object(),
        stt_provider=object(),
        on_command=lambda _text: None,
        on_log=lambda _text: None,
        on_state=lambda _state: None,
        detector=detector,
    )


def test_stream_detector_uses_single_pcm_frame() -> None:
    detector = _Detector(result=True)
    listener = _listener(detector)
    frames: queue.Queue[bytes] = queue.Queue()
    frame = b"\x00\x00" * 1280
    frames.put(frame)

    assert listener._wait_for_wake_word(frames) is True
    assert detector.frames == [frame]


def test_speech_endpointing_stops_after_silence() -> None:
    listener = _listener()
    listener._stt_provider = SimpleNamespace(transcribe=lambda _request: _transcript("включи свет"))
    frames: queue.Queue[bytes] = queue.Queue()
    speech = (500).to_bytes(2, "little", signed=True) * 1280
    silence = b"\x00\x00" * 1280
    frames.put(speech)
    for _ in range(10):
        frames.put(silence)

    assert listener._transcribe_command(frames) == "включи свет"
    assert frames.qsize() == 0


async def _transcript(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)