# Wave 18 realtime inventory

Audit base: `eb0b045`, branch `integration/main`, clean. Focused baseline:
106 passed, 0 failed.

| Task | Before | Implemented acceptance boundary |
| --- | --- | --- |
| W18-T01 | Partial | Typed monotonic latency events, provider activity-end capture when emitted, approval/handler separation; unavailable VAD end remains absent rather than fabricated. |
| W18-T02 | Partial | AgentLoop timeouts retained; Live connect and outbound send operations bounded; cancellation still owns cleanup. Long-lived receive is intentionally not idle-timed out. |
| W18-T03 | Partial | Existing bounded drop-oldest queues/generations retained; callback ingress is coalesced to one pending frame; explicit server-activity echo mode. |
| W18-T04 | Partial | `side_effect_class` and fail-closed metadata validation; only distinct, read-only, idempotent, side-effect-free calls may run concurrently. |
| W18-T05 | Not started | Canonical payload-free runtime event bus plus compatibility UI/control-plane sink. |
| W18-T06 | Not started | Scenario-labelled benchmark API with warmup, N, environment, definition and nearest-rank p90/p95. |

## Runtime map

Microphone callback → coalesced loop ingress → bounded fresh mic queue → timed
Gemini send → Live receive → generation-tagged bounded playback queue → off-loop
device write. Provider interruption invalidates queued playback and emits a
cancelled runtime event. Tool calls remain SafetyPolicy-gated and publish only
metadata start/finish events.

## Explicit limitations

- Exact server speech-end/VAD is recorded only when Gemini emits activity-end;
  otherwise it is unavailable. `input_first_chunk_to_response` is not VAD latency.
- A blocking legacy handler may outlive its timeout and is never automatically
  retried. Cancellation cannot make an already-started side effect reversible.
- Playback already submitted to the device may produce a short audible tail.
- Human microphone, echo, soak, and barge-in validation remains pending.
- Cloud and real-voice benchmark samples require their real environments; the
  harness never substitutes fake samples for production measurements.
