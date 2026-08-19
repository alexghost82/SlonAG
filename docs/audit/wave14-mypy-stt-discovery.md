# Wave 14 — mypy / STT mic / Bonjour+QR+live video

Personal / non-commercial. Local Git only; push only to `alexghost82` when requested.

## Delivered

| Item | Status |
|---|---|
| mypy | **0 errors** on configured `files` (mypy 1.14.1 / Py3.12) |
| STT mic | `speech/stt/mic.py`, engines, `local_factory`; UI **LOCAL STT LISTEN**; echo-guard hook |
| Bonjour | `server/bonjour.py`; `--bonjour` / UI advertise; iOS `BonjourBrowser` |
| QR images | `server/qr.py` + `qr_png_base64` on pairing start; iOS `PairingQRCodeView` |
| Live video | `GET /v1/screen/frame` (JPEG) + `GET /v1/screen/stream` (MJPEG); mss grab |

## Usage

```bash
python -m server --bonjour
python -m server --host 192.168.x.x --allow-non-loopback --bonjour --tls --tls-generate
# Live view (auth Bearer required):
#   curl -H "Authorization: Bearer …" http://HOST:8765/v1/screen/stream
```

Optional ASR: `pip install openai-whisper` (not required for mic capture).

## Deps

`qrcode`, `zeroconf` added to `requirements-base.txt`.
