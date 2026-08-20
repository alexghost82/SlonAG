# ADR 0001: Payload-free realtime event boundary

- Status: Accepted
- Date: 2026-08-20
- Wave: 18

## Context

The Live lifecycle, audio pipeline, and tool bridge updated the desktop UI
imperatively. That made state transitions observable, but there was no shared
contract for ordering, correlation, cancellation, or headless consumers.
Provider `ChatEvent` is a provider-stream contract and must not become a UI
contract.

## Decision

Runtime producers publish immutable `RuntimeEvent` values through one
`RuntimeEventBus`. Events carry a monotonic timestamp, monotonically increasing
sequence, optional turn/tool correlation, bounded progress, and sanitized status
codes. They never carry transcripts, tool arguments/results, credentials, or raw
audio. The existing UI is retained behind `UIRuntimeEventSink`; sink failures are
isolated from the realtime path.

The bus performs small synchronous fan-out. Subscribers must remain non-blocking;
slow transports must add their own bounded/coalescing adapter. This avoids adding
an unbounded queue to the audio path.

## Consequences

- Runtime state is testable without PyQt or a network transport.
- UI and control-plane consumers see the same ordered metadata.
- Existing UI behavior remains compatible.
- The bus does not provide replay or delivery guarantees; those belong in a
  bounded adapter if required later.

## Fitness functions

- Event sequences and timestamps are monotonic.
- Required event kinds are finite and validated.
- Events expose no payload fields.
- A failing subscriber cannot stop later subscribers or the runtime.
- Tool events preserve call correlation.

## Rollback

Remove the bus wiring and return producers to direct `ui.set_state` calls. No
provider, audio, tool, or storage contract depends on event persistence.

