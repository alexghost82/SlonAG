# WAVE R6 — Gateway / Sessions

**WAVE:** R6  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-034 | `gateway/*` vs `server/*` | Dual API unclear | Documented: Gateway is the only remote iOS security boundary. `server/*` remains local desktop `/v1`. TLS/pairing/Ed25519/pinning/rate-limit/replay **not** weakened. |
| SLON-034 | sessions lifecycle | expire + crash/resume suite incomplete | `SessionManager.expire_idle`. Tests: crash recover + resume history, duplicate tool events idempotent, disconnect-during-tool cancel, expire, workspace isolation. |
| SLON-034 | gateway reconnect | reconnect/malformed/backpressure not all in one place | Tests: reconnect replay after disconnect, backpressure closes slow client, malformed/large frames fail closed. Existing suite already covers pairing replay and oversized frames. |

## REMOVED LEGACY

None. Legacy `/v1` listener retained as local desktop API.

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/unit/sessions/test_session_lifecycle_r6.py tests/unit/gateway/test_gateway_lifecycle_r6.py -q` | **8 passed** |
| `python -m pytest tests/unit/sessions/test_session_lifecycle_r6.py tests/unit/gateway/test_gateway_lifecycle_r6.py tests/unit/sessions/test_session_engine.py tests/unit/gateway/test_gateway.py -q` | **54 passed** after one test fix (duplicate tool append is idempotent in store) |

## SECURITY

- No change to pairing, TLS, Ed25519, nonce, or rate limits.
- Foreign workspace cannot resume.
- Oversized/malformed frames still fail closed.

## MIGRATIONS

None.

## KNOWN LIMITATIONS

- iOS LAN hardware reconnect not run (sibling `ios/**`, MANUAL).
- Session idle expiry is manager-level (updated_at), not a new DB column.

## RUNTIME VERIFICATION STILL REQUIRED

- Real iOS device pairing + TLS pin + disconnect mid-tool.

## COMMITS

Recorded after commit.
