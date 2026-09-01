"""Deterministic RTSP fixture.

Creates a mock RTSP server that serves known test frames over TCP,
enabling deterministic E2E testing of the RTSP frame acquisition path.
"""

from __future__ import annotations

import asyncio

import cv2 as cv  # type: ignore[import-untyped]
import numpy as np  # type: ignore[import-untyped]


class RTSPFixture:
    """Mock RTSP server for deterministic testing.

    Serves pre-generated test frames over an RTSP-like TCP interface.
    Used by E2E tests that need to exercise the RTSP acquisition path
    without requiring a real camera or FFmpeg RTSP server.

    Parameters
    ----------
    port : int
        TCP port to listen on (default 8554).
    width, height : int
        Frame dimensions (default 640x480).
    fps : float
        Frame rate (default 10.0).
    num_frames : int
        How many frames to cycle through (default 20).
    """

    def __init__(
        self,
        port: int = 8554,
        width: int = 640,
        height: int = 480,
        fps: float = 10.0,
        num_frames: int = 20,
    ) -> None:
        self.port = port
        self.width = width
        self.height = height
        self.fps = fps
        self.num_frames = num_frames
        self._frames: list[bytes] = []
        self._running = False
        self._server: asyncio.Task | None = None
        self._frame_index = 0

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> RTSPFixture:
        """Start the mock RTSP server. Returns self for chaining."""
        self._generate_frames()
        self._running = True
        try:
            self._server = asyncio.create_task(self._serve())
            await asyncio.sleep(0.2)  # let server bind
        except Exception:
            self._running = False
        return self

    async def stop(self) -> None:
        """Stop the mock RTSP server."""
        self._running = False
        if self._server is not None:
            self._server.cancel()
            try:
                await self._server
            except asyncio.CancelledError:
                pass
            self._server = None

    @property
    def url(self) -> str:
        return f"rtsp://localhost:{self.port}/live"

    # ── frame generation ─────────────────────────────────────────

    def _generate_frames(self) -> None:
        """Generate deterministic test frames."""
        self._frames = []
        for i in range(self.num_frames):
            frame = np.full((self.height, self.width, 3),
                            [30 + i * 5, 60, 120], dtype=np.uint8)
            # Moving rectangle
            x = 50 + i * ((self.width - 150) // self.num_frames)
            y = 100 + i * 5
            cv.rectangle(frame, (x, y), (x + 80, y + 60),
                         (220, 50, 50), 2)
            # Frame counter
            cv.putText(frame, f"FR{i}", (10, 30),
                       cv.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            success, buf = cv.imencode(".jpg", frame)
            if success:
                self._frames.append(buf.tobytes())

    def _get_frame(self) -> bytes | None:
        """Get the next deterministic frame."""
        if not self._frames:
            return None
        frame = self._frames[self._frame_index % len(self._frames)]
        self._frame_index += 1
        return frame

    # ── server loop ──────────────────────────────────────────────

    async def _serve(self) -> None:
        """Serve frames over TCP (simplified RTSP-like protocol)."""
        server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self.port,
        )
        try:
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            server.close()
            await server.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        """Handle a single client connection.

        Waits for an initial HTTP request then continuously streams frames.
        """
        try:
            # Wait for initial HTTP request from the client
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            if not data:
                return

            # Stream frames continuously without waiting for further requests
            while self._running:
                frame = self._get_frame()
                if frame is not None:
                    size = len(frame).to_bytes(4, "big")
                    writer.write(size + frame)
                    await writer.drain()
                await asyncio.sleep(1.0 / self.fps)
        except (TimeoutError, ConnectionResetError):
            pass
        finally:
            writer.close()


def create_rtsp_fixture(
    port: int = 8554,
    width: int = 640,
    height: int = 480,
    fps: float = 10.0,
    num_frames: int = 20,
) -> RTSPFixture:
    """Convenience factory."""
    return RTSPFixture(port, width, height, fps, num_frames)
