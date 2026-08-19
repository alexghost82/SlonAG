# Same-LAN Desktop Control API bind (operator notes)

Personal / non-commercial use. This is **not** a public-internet, VPN, or APNs
product. Pairing and auth remain mandatory on every bind mode.

## Defaults (secure)

| Setting | Default | Meaning |
|---|---|---|
| `bind_host` | `127.0.0.1` | Loopback only |
| `allow_non_loopback` | `False` | Same-LAN opt-in off |
| Mock (`DesktopControlApp`) | no sockets | In-process only; `listening` stays False |
| Live (`DesktopControlListener`) | explicit `start()` | Real `socket.listen` after start |

Wildcards (`0.0.0.0`, `::`) are **always** rejected.

## Start / stop (live listener)

CLI (loopback default):

```bash
python -m server
python -m server --host 127.0.0.1 --port 8765
python -m server --host 192.168.1.20 --port 8765 --allow-non-loopback
```

Desktop UI (`ui.py`): use **DESKTOP API** toggle in the right panel (loopback
`127.0.0.1:8765`). Closing the window stops the listener.

Programmatic:

```python
from server.listener import DesktopControlListener

listener = DesktopControlListener(
    bind_host="192.168.1.20",
    allow_non_loopback=True,
    bind_port=8765,
)
host, port = listener.start()  # real bind + listen
# … pair via POST /v1/pairing/start + /complete, then POST /v1/auth/token …
listener.stop()
```

Policy lives in `server/bind_policy.py`. Public addresses and wildcards remain
denied even with the LAN opt-in flag.

## Same-LAN opt-in (iPhone on Wi‑Fi)

1. On the Mac/desktop, note a **private** IPv4 on the same Wi‑Fi as the iPhone,
   for example `192.168.1.20` (also `10.0.0.0/8` or `172.16.0.0/12`).
2. Start the live listener with that address **and** `--allow-non-loopback`
   (or `allow_non_loopback=True`).
3. Complete **pairing** (`/v1/pairing/start` → `/v1/pairing/complete`) then
   mint a Bearer token (`/v1/auth/token` with `device_id` + `device_secret`).
4. Point the iOS Mark Remote client at `http://<desktop-lan-ip>:8765`
   (TLS for production is a separate hard requirement; this personal listener
   is HTTP for local LAN bring-up).

## What this does not claim

- No “open to the internet”
- No VPN tunnel product
- No APNs / push product
- No anonymous / unauthenticated LAN access

## Auth reminder

Unauthenticated `/v1/status` and `/v1/events` still return 401. Mutating routes
still require pairing completion and idempotency keys as implemented in Wave 9.
The live listener uses real `PairingService` + `TokenService` + route handlers;
the mock `DesktopControlApp` remains available for in-process unit tests.
