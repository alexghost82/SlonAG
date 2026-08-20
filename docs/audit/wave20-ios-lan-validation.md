# Wave 20 LAN/iOS validation runbook

Status: `W20_IOS_LAN_VALIDATION: PENDING`. The existing iOS client uses the
legacy Desktop Control protocol; a Gateway-compatible client belongs to Wave
21. Do not count localhost tests as iOS validation.

1. Create or supply a certificate whose SAN contains the exact private LAN IP.
2. Start the opt-in Gateway from the trusted Mac terminal:

```bash
cd /Users/slon/Documents/GitHub/Slon
.venv/bin/python -m server \
  --gateway-lan --gateway-pair \
  --host <PRIVATE_LAN_IP> --port 8765 \
  --allow-non-loopback --tls \
  --tls-cert models/certs/desktop-control.crt \
  --tls-key models/certs/desktop-control.key \
  --repo-root /Users/slon/Documents/GitHub/Slon
```

3. Verify the terminal and Desktop UI report `Gateway LAN RUNNING`, the exact
   private IP, and TLS. Transfer the one-time pairing code locally; it is never
   available from an unauthenticated endpoint.
4. With a compatible iOS client, pin the TLS certificate and Ed25519 device
   key, authenticate, connect `/v1/gateway/ws`, then create/resume a Session.
5. Run a normal request and a read-only tool. For a reversible side effect,
   verify DENY executes zero times and ALLOW executes once.
6. ACK the latest event, disconnect, produce another event, reconnect without
   a forged cursor, and verify only unacknowledged events replay.
7. Revoke the device and verify the active socket loses authority. Re-pair only
   through a newly displayed local code.
8. Verify access expiry closes authority, refresh rotates once, and the prior
   access/refresh credentials are rejected after restart.
9. Confirm the listener is bound only to the selected private IP and no UPnP,
   forwarding, reverse proxy, tunnel, relay, wildcard or public bind exists.

Do not retain pairing codes, tokens, private keys, transcripts or raw tool
arguments in validation notes.
