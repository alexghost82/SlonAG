# Wave 20 Gateway inventory

Audit base: `e4729bb`, branch `integration/main`. Baseline: 949 passed; focused
Gateway prerequisite baseline: 160 passed.

| Task | Initial | Existing foundation | Initial gap |
| --- | --- | --- | --- |
| W20-T01 | Not started | Legacy REST schemas and payload-free RuntimeEvent | No canonical Gateway envelope. |
| W20-T02 | Partial | One-time pairing, hashed secrets, rotating tokens, revocation, TLS fingerprint | No pinned device key or durable trusted list. |
| W20-T03 | Partial | Authenticated outbound-only `/v1/events` WebSocket | No duplex codec, cursor, sequence replay or bounded backpressure. |
| W20-T04 | Not started | Legacy resource routes and RuntimeStack/SessionManager | No official namespaced router. |
| W20-T05 | Partial | Allowlisted inline file upload with size cap | No signed short-lived transfer grant/download. |
| W20-T06 | Not started | Durable logical SessionStore only | Gateway devices/connections/cursors/approvals/jobs were volatile. |
| W20-T07 | Partial | Legacy auth/TLS/upload tests | Missing Gateway protocol/replay/backpressure/pinning tests. |

## Production boundaries

The Gateway is not a channel gateway. Its untrusted boundary is TLS WebSocket
control plus HTTPS artifact bytes. Strict Gateway envelopes are decoded before
routing. Device identity is derived from a pinned Ed25519 key and rotating
access credentials; workspace ownership is read from the trusted-device store,
never an envelope payload.

The namespaced router delegates to public SessionManager, RuntimeStack and
approval adapters. It cannot access tool handlers. RuntimeEvent values are
converted to sanitized Gateway envelopes by an outbound adapter; internal
monotonic timestamps remain internal.

Gateway SQLite owns trusted devices, device connections, event sequence/cursor,
pending operations, request replay records and artifact grants. It stores no
conversation transcript. Startup marks pending/running work interrupted and
never repeats the business operation.

## Queue and replay policy

Each connection has a fixed outbound capacity. Overflow closes only the slow
connection instead of dropping control state or blocking runtime producers.
Published events receive a durable sequence; reconnect requests events after a
cursor. An acknowledgement can only move its cursor forward. Replayed request
IDs return a completed cached response or fail closed when the prior outcome is
uncertain.

## Compatibility

The existing `/v1` Desktop Control listener, Gemini Live transport, RuntimeEvent
bus, Session Engine and all Wave 16–19 adapters remain unchanged. They can be
removed only after their callers migrate independently.

## Acceptance status

Implemented and automated: strict envelopes, pinned Ed25519 device identity,
durable refresh rotation/access replay protection, trusted-device revocation,
duplex bounded WebSocket transport, delivered-only ACK cursors, reconnect
replay, signed owner-scoped artifacts, Session routes, AgentLoop binding,
durable job records, and factual node/automation inventory.

The LAN/iOS entrypoint is opt-in (`--gateway-lan`), accepts only an explicit
private address, requires `--allow-non-loopback --tls`, and never configures a
reverse proxy, wildcard bind, UPnP, forwarding, tunnel or cloud relay. Pairing
codes are created and displayed only on the trusted local process with
`--gateway-pair`; no unauthenticated endpoint can mint/read a code.

Human TLS/LAN/iOS validation remains pending. Approval persistence currently
backs Gateway-native approval operations; the legacy Desktop Control approval
waiter remains a compatibility adapter and is not replayed after restart.
