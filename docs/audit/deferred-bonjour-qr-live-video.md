# Bonjour, QR images, live video (Wave 14)

Previously deferred in Wave 13; **implemented** for personal/non-commercial LAN use.

| Item | Implementation |
|---|---|
| Bonjour / mDNS | Desktop: `server/bonjour.py` (`zeroconf` or macOS `dns-sd`). CLI `--bonjour`. iOS: `BonjourBrowser`. |
| QR images | Desktop: `server/qr.py` → `qr_png_base64` in pairing start. iOS: CoreImage `PairingQRCodeView`. Text payload remains. |
| Live video | `GET /v1/screen/frame` (single JPEG) and `GET /v1/screen/stream` (MJPEG ~2 fps). Auth required. Not public internet. |

Epic 14 (VPN / APNs / public bind) remains deferred.
