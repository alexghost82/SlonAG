# TLS for Desktop Control API (LAN / loopback)

Personal / non-commercial. Not a public-internet product (Epic 14 still deferred).

## Behavior

- Default: plain **HTTP** on loopback (`127.0.0.1:8765`) — unchanged.
- Opt-in HTTPS: pass cert + key into `DesktopControlListener`, or CLI:

```bash
python -m server --tls --tls-generate
python -m server --tls --tls-cert models/certs/desktop-control.crt \
  --tls-key models/certs/desktop-control.key
python -m server --host 192.168.1.20 --allow-non-loopback --tls --tls-generate
```

- `bind_policy` still rejects wildcards / public binds.
- Auth and pairing remain mandatory on `/v1/*` protected routes.
- When TLS is enabled, plain HTTP clients to that port fail (TLS-only socket).

## Cert material

Default layout (gitignored under `/models/`):

```text
models/certs/desktop-control.crt
models/certs/desktop-control.key
```

`--tls-generate` runs `openssl req -x509` (self-signed, CN=`mark-desktop.local`).
Never commit certs or keys.

### mkcert (recommended for iOS trust)

```bash
brew install mkcert
mkcert -install
mkdir -p models/certs
mkcert -cert-file models/certs/desktop-control.crt \
  -key-file models/certs/desktop-control.key \
  mark-desktop.local 127.0.0.1 localhost
```

Install the mkcert root CA on the iPhone (AirDrop / Profiles) so Safari /
MarkRemote can trust the LAN host without disabling TLS verification.

### Self-signed without mkcert

1. Generate with `--tls-generate`.
2. On iOS: Settings → General → VPN & Device Management → install the `.crt`,
   then Certificate Trust Settings → enable full trust for that root/cert.
3. Pair using the existing one-time code / `mark-pair://` text payload over
   `https://<lan-ip>:8765`.

## Library

```python
from server.tls import ensure_tls_material
from server.listener import DesktopControlListener

material = ensure_tls_material(repo_root=".", generate=True)
listener = DesktopControlListener(
    tls_certfile=material.certfile,
    tls_keyfile=material.keyfile,
    require_tls=True,
)
```
