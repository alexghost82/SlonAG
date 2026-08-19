"""Live screen JPEG frames for same-LAN remote view (mss). Personal use only."""

from __future__ import annotations

import io
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

DEFAULT_FPS = 2.0
DEFAULT_JPEG_QUALITY = 60
MAX_FPS = 8.0


class ScreenGrabError(RuntimeError):
    """Framebuffer capture failed."""


@dataclass(frozen=True)
class Frame:
    """One JPEG frame."""

    jpeg: bytes
    width: int
    height: int
    seq: int
    ts: float


GrabFn = Callable[[], tuple[bytes, int, int]]


def _mss_grab(quality: int = DEFAULT_JPEG_QUALITY) -> tuple[bytes, int, int]:
    try:
        import mss
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        raise ScreenGrabError(f"mss/Pillow unavailable: {exc}") from exc
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(quality))
        return buf.getvalue(), int(shot.width), int(shot.height)


class LiveVideoSource:
    """Rate-limited JPEG frame source for MJPEG / polling."""

    def __init__(
        self,
        *,
        fps: float = DEFAULT_FPS,
        quality: int = DEFAULT_JPEG_QUALITY,
        grab: GrabFn | None = None,
    ) -> None:
        self.fps = min(MAX_FPS, max(0.2, float(fps)))
        self.quality = quality
        self._grab = grab or (lambda: _mss_grab(self.quality))
        self._lock = threading.Lock()
        self._seq = 0
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def grab_one(self) -> Frame:
        jpeg, width, height = self._grab()
        with self._lock:
            self._seq += 1
            seq = self._seq
        return Frame(jpeg=jpeg, width=width, height=height, seq=seq, ts=time.time())

    def frames(self) -> Iterator[Frame]:
        interval = 1.0 / self.fps
        while not self._stopped:
            started = time.monotonic()
            yield self.grab_one()
            elapsed = time.monotonic() - started
            delay = interval - elapsed
            if delay > 0:
                time.sleep(delay)


def mjpeg_bytes(frame: Frame) -> bytes:
    """One multipart MJPEG part (caller wraps boundary)."""
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: "
        + str(len(frame.jpeg)).encode("ascii")
        + b"\r\n\r\n"
        + frame.jpeg
        + b"\r\n"
    )


__all__ = [
    "DEFAULT_FPS",
    "Frame",
    "LiveVideoSource",
    "ScreenGrabError",
    "mjpeg_bytes",
]
