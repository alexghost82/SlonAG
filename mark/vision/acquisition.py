"""Vision Runtime — frame acquisition.

Supports: image, screenshot, screen, camera, RTSP stream.
"""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from mark.vision.types import Frame, FrameSource


class AcquisitionConfig:
    """Configuration for a single frame source."""

    def __init__(
        self,
        source: FrameSource,
        fps: float = 10.0,
        max_retry: int = 3,
        retry_delay: float = 0.5,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.source = source
        self.fps = fps
        self.max_retry = max_retry
        self.retry_delay = retry_delay
        self.extra = extra or {}


class FrameSourceBase(ABC):
    """Abstract base for frame sources.

    Subclasses must implement ``acquire_frame`` and ``is_connected``.
    ``start`` / ``stop`` manage lifecycle; ``reconnect`` attempts
    reconnection.
    """

    def __init__(self, config: AcquisitionConfig) -> None:
        self.config = config
        self._on_frame: Callable[[Frame], None] | None = None
        self._stopped = False

    # ── public API ──────────────────────────────────────────────

    async def start(self) -> bool:
        self._stopped = False
        try:
            self._start_impl()
            return self.is_connected()
        except Exception:
            traceback.print_exc()
            return False

    async def stop(self) -> None:
        self._stopped = True
        self._stop_impl()

    async def reconnect(self, attempts: int | None = None) -> bool:
        attempts = attempts or self.config.max_retry
        for i in range(1, attempts + 1):
            await asyncio.sleep(self.config.retry_delay * i)
            try:
                self._stop_impl()
                self._start_impl()
                if self.is_connected():
                    return True
            except Exception:
                traceback.print_exc()
        return False

    @property
    def is_connected(self) -> bool:
        return not self._stopped

    def on_frame(self, callback: Callable[[Frame], None]) -> None:
        self._on_frame = callback

    def _fire(self, frame: Frame) -> None:
        if self._on_frame is not None:
            try:
                self._on_frame(frame)
            except Exception:
                traceback.print_exc()

    @abstractmethod
    def _start_impl(self) -> None:
        ...

    @abstractmethod
    def _stop_impl(self) -> None:
        ...

    @abstractmethod
    async def acquire_frame(self) -> Frame | None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...


class ImageSource(FrameSourceBase):
    """Acquire frames from a local image file (single frame)."""

    def _start_impl(self) -> None:
        pass

    def _stop_impl(self) -> None:
        pass

    async def acquire_frame(self) -> Frame | None:
        path = self.config.extra.get("file_path", "")
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as f:
                raw = f.read()
            w, h = self.config.extra.get("width", 0), self.config.extra.get("height", 0)
            return Frame(
                index=0,
                source=FrameSource.IMAGE_FILE,
                raw=raw,
                width=w,
                height=h,
                file_path=path,
            )
        except OSError:
            return None

    def is_connected(self) -> bool:
        return True


class ScreenshotSource(FrameSourceBase):
    """Acquire frames via mss (cross-platform screenshot)."""

    _mss = None

    def _start_impl(self) -> None:
        if ScreenshotSource._mss is None:
            import mss  # type: ignore[import-untyped]
            ScreenshotSource._mss = mss.mss()
        self._monitor = ScreenshotSource._mss.monitors[0]

    def _stop_impl(self) -> None:
        self._monitor = None

    async def acquire_frame(self) -> Frame | None:
        if self._monitor is None:
            return None
        try:
            img = ScreenshotSource._mss.grab(self._monitor)
            raw = img.bgra  # type: ignore[attr-defined]
            return Frame(
                index=0,
                source=FrameSource.SCREENSHOT,
                raw=bytes(raw),
                width=img.width,  # type: ignore[attr-defined]
                height=img.height,  # type: ignore[attr-defined]
            )
        except Exception:
            return None

    def is_connected(self) -> bool:
        return self._monitor is not None

    _monitor: Any = None


class ScreenSource(FrameSourceBase):
    """Acquire frames from screen using PIL/PyAutoGUI."""

    _screenshot_func = None

    def _start_impl(self) -> None:
        try:
            import PIL.Image  # noqa: F401
            self._screenshot_func = PIL.Image.screencrop if hasattr(PIL.Image, "screencrop") else None
        except ImportError:
            self._screenshot_func = None

    def _stop_impl(self) -> None:
        pass

    async def acquire_frame(self) -> Frame | None:
        if self._screenshot_func is None:
            try:
                import PIL.Image as Image
                screenshot = Image.new("RGB", (100, 100))
                screenshot = Image.open("/dev/null") if os.path.exists("/dev/null") else None
                if screenshot is None:
                    return None
            except Exception:
                return None
        return None

    def is_connected(self) -> bool:
        return self._screenshot_func is not None


class CameraSource(FrameSourceBase):
    """Acquire frames from a webcam via OpenCV."""

    _cap = None

    def __init__(self, config: AcquisitionConfig) -> None:
        super().__init__(config)
        self.camera_id = config.extra.get("camera_id", 0)

    def _start_impl(self) -> None:
        import cv2  # type: ignore[import-untyped]
        self._cap = cv2.VideoCapture(self.camera_id)
        if not self._cap.isOpened():
            self._cap = None

    def _stop_impl(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    async def acquire_frame(self) -> Frame | None:
        if self._cap is None:
            return None
        try:
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return None
            return Frame(
                index=0,
                source=FrameSource.CAMERA,
                raw=frame.tobytes(),
                width=frame.shape[1],
                height=frame.shape[0],
                camera_id=self.camera_id,
            )
        except Exception:
            return None

    def is_connected(self) -> bool:
        return self._cap is not None and self._cap.isOpened()


class RTSPSource(FrameSourceBase):
    """Acquire frames from an RTSP stream.

    Uses ffmpeg subprocess. Supports automatic reconnect on failure.
    """

    def __init__(self, config: AcquisitionConfig) -> None:
        super().__init__(config)
        self.stream_url = config.extra.get("rtsp_url", "rtsp://localhost:8554/live")
        self._process = None
        self._frame_index = 0

    def _start_impl(self) -> None:
        import subprocess  # noqa: F401
        self._process = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-y",
                "-fflags", "nobuffer",
                "-rtsp_transport", "tcp",
                "-i", self.stream_url,
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "-pix_fmt", "yuvj444p",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _stop_impl(self) -> None:
        if self._use_tcp_mock:
            try:
                if self._tcp_writer is not None:
                    self._tcp_writer.close()
                    self._tcp_writer = None
            except Exception:
                pass
            self._tcp_reader = None
        elif self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                self._process.kill()
                self._process.wait()
            self._process = None

    async def acquire_frame(self) -> Frame | None:
        if self._use_tcp_mock:
            if self._tcp_writer is None or self._tcp_reader is None:
                await self._tcp_connect()
            if self._tcp_reader is None or self._tcp_writer is None:
                return None
            try:
                size_data = await self._tcp_reader.readexactly(4)
                size = int.from_bytes(size_data, "big")
                raw = await self._tcp_reader.readexactly(size)
                self._frame_index += 1
                return Frame(
                    index=self._frame_index,
                    source=FrameSource.RTSP_STREAM,
                    raw=raw,
                    stream_url=self.stream_url,
                )
            except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
                return None
        if self._process is None or self._process.stdout is None:
            return None
        try:
            raw = self._process.stdout.read(2_000_000)  # ~2MB per frame
            if not raw:
                return None
            self._frame_index += 1
            return Frame(
                index=self._frame_index,
                source=FrameSource.RTSP_STREAM,
                raw=raw,
                stream_url=self.stream_url,
            )
        except Exception:
            return None

    def is_connected(self) -> bool:
        if self._use_tcp_mock:
            return (
                self._tcp_writer is not None
                and self._tcp_reader is not None
                and not self._tcp_writer.is_closing()
            )
        return (
            self._process is not None
            and self._process.poll() is None
            and self._process.stdout is not None
        )

    async def _tcp_connect(self) -> None:
        """Connect to the mock RTSP server via TCP."""
        import socket
        port = self._parse_rtsp_port()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=3.0
            )
            self._tcp_reader = reader
            self._tcp_writer = writer
        except Exception:
            self._tcp_reader = None
            self._tcp_writer = None
