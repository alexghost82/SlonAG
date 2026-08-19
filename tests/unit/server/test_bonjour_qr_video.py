"""Bonjour / QR / live-video unit tests (no real network or display required)."""

from __future__ import annotations

import pytest

from server.bonjour import BonjourError, BonjourManager, start_bonjour
from server.live_video import Frame, LiveVideoSource, mjpeg_bytes
from server.qr import QrRenderError, render_qr_png, try_render_qr_png


def test_qr_render_or_skip_when_missing() -> None:
    png = try_render_qr_png("mark-pair://local/TEST")
    if png is None:
        pytest.skip("qrcode not installed")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert render_qr_png("mark-pair://local/TEST").startswith(b"\x89PNG")


def test_qr_empty_payload_raises() -> None:
    with pytest.raises(QrRenderError):
        render_qr_png("")


def test_live_video_injected_grab() -> None:
    calls = {"n": 0}

    def grab():
        calls["n"] += 1
        return b"JPEGDATA", 320, 240

    src = LiveVideoSource(fps=10.0, grab=grab)
    frame = src.grab_one()
    assert isinstance(frame, Frame)
    assert frame.jpeg == b"JPEGDATA"
    assert frame.width == 320
    assert calls["n"] == 1
    part = mjpeg_bytes(frame)
    assert part.startswith(b"--frame\r\n")
    assert b"JPEGDATA" in part


def test_bonjour_invalid_port() -> None:
    with pytest.raises(BonjourError):
        start_bonjour("127.0.0.1", 0)


def test_bonjour_manager_stop_idempotent() -> None:
    mgr = BonjourManager()
    mgr.stop()
    assert mgr.active is False
