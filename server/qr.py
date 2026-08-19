"""QR code image rendering for pairing payloads (Pillow + qrcode)."""

from __future__ import annotations

import io
from typing import Any


class QrRenderError(RuntimeError):
    """QR library missing or encode failed."""


def render_qr_png(payload: str, *, box_size: int = 6, border: int = 2) -> bytes:
    """Return PNG bytes for ``payload``. Requires ``qrcode`` + Pillow."""
    if not payload:
        raise QrRenderError("empty QR payload")
    try:
        import qrcode
    except Exception as exc:  # noqa: BLE001
        raise QrRenderError(f"qrcode package unavailable: {exc}") from exc
    try:
        qr = qrcode.QRCode(border=border, box_size=box_size)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise QrRenderError(f"QR encode failed: {exc}") from exc


def try_render_qr_png(payload: str, **kwargs: Any) -> bytes | None:
    """Best-effort PNG; ``None`` when qrcode is missing."""
    try:
        return render_qr_png(payload, **kwargs)
    except QrRenderError:
        return None


__all__ = ["QrRenderError", "render_qr_png", "try_render_qr_png"]
