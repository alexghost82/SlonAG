# ADR 0003: Authenticated durable Gateway boundary

- Status: Accepted
- Date: 2026-08-20
- Wave: 20

## Context

Desktop Control already provides loopback/LAN HTTP primitives, while Waves
16–19 own tools, providers, realtime events and durable logical sessions. The
always-on iOS control plane needs replay, device trust and artifact transfer
without turning any internal contract into a network protocol.

## Decision

`gateway` is a distinct anti-corruption boundary. TLS WebSocket carries strict
versioned `GatewayEnvelope` values and HTTPS carries signed artifact transfers.
The Gateway authenticates a pinned device key, authorizes a server-owned
workspace, and delegates through public `SessionManager`, `RuntimeStack` and
approval interfaces. It never invokes tool handlers directly.

Gateway state has a separate transactional SQLite store for trusted devices,
device connections, replay cursors, event sequence records, pending approvals,
jobs, artifact grants and request idempotency. It references logical session
IDs but does not duplicate Session transcripts. Runtime events remain
payload-free and are converted by a bounded transport adapter.

Every client queue is bounded. Overflow terminates the affected connection;
terminal/control state is never silently dropped. Reconnect replays events
after a cursor, but never replays a command, approval or uncertain side effect.
Existing `/v1` Desktop Control routes remain compatibility APIs.

## Consequences

- Gateway/network concepts do not leak into sessions, providers or tools.
- Device revocation, cursors and pending state survive restart.
- One slow client cannot block the runtime or another client.
- Gateway storage is a distinct bounded context and contains no transcripts.
- Legacy Desktop Control remains until callers migrate to Gateway envelopes.

## Fitness functions

- `sessions`, `runtime`, `providers` and `mark.tools` never import `gateway`.
- Envelope decoding is strict and bounded before routing.
- Event sequences are durable and monotonic; queues have explicit capacity.
- Workspace/session authorization is server-derived and fail-closed.
- Device key mismatch, expired/revoked tokens and replay are rejected.
- Artifact grants are device-bound, expiring, signed and size/type limited.
- Recovery never retries jobs, approvals or tool side effects.

## Rollback

Stop composing the Gateway and retain the existing local Desktop Control API.
Gateway storage is additive; no SessionStore or runtime schema is migrated.
