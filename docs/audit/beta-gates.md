# Beta gates checklist — Slon Wave 11

This document records verification for a **personal / non-commercial beta** under
CC BY-NC 4.0. It is **not** a commercial-readiness claim.

Status vocabulary:

- **pass** — verified in this wave
- **fail** — verified broken; must be fixed before claiming the gate
- **deferred** — intentionally out of scope or blocked on a user decision

## Automated suites (Wave 11 acceptance)

| Gate | Status | Notes |
|---|---|---|
| Unit + gates (`pytest -q`) | **pass** | **597 passed, 1 skipped**, 2 warnings (Gemini `asyncio.iscoroutinefunction` deprecation) |
| Integration (`tests/integration`) | **pass** | 5 smokes: loopback bind, unauth 401, no listen, no API keys in status, NetworkPolicy×SafetyPolicy |
| Security (`tests/security`) | **pass** | 10 smokes: injection wrap, traversal, SSRF, unknown-tool, no codegen, reminder `shell=False`, desktop op reject, no secrets in API |
| Offline (`tests/offline`) | **pass** | W08 network offline + 2 W11 SafetyPolicy/NetworkPolicy offline smokes |
| iOS (`cd ios && swift test`) | **pass** | **71 XCTest passed, 0 failures** (Networking 15 + Features 46 + DesignSystem 10); `DEVELOPER_DIR` = Xcode-beta |
| Lint (`ruff check tests`) | **pass** | All checks passed |
| Typecheck (`mypy`) | **deferred** | Pre-existing: **133 errors in 36 files** (93 sources checked); not cleaned in Wave 11 |
| Secret scan (tracked tree) | **pass** | No live keys outside `tests/`; fixtures use fake sentinels only. Upstream `ui.py` still has an `sk-or` placeholder substring (pre-existing; not a live key). |
| License audit | **pass** | CC BY-NC 4.0 recorded; docs state **not** commercially ready; Piper MIT runtime + `ru_RU-dmitri-medium` documented in `docs/licenses/piper.md` (W12-T01) |

## Explicitly deferred / blocked

| Item | Status | Reason |
|---|---|---|
| Piper TTS | **pass (W12)** | Implemented in `W12-T01`: injectable `PiperSpeechSynthesizer` + `ru_RU-dmitri-medium`; no auto-download |
| Same-LAN Desktop API bind | **pass (W12)** | Implemented in `W12-T02`: `server/bind_policy.py`; loopback default; RFC1918 opt-in; wildcards/public denied; auth unchanged |
| Push / APNs / VPN product / public internet | deferred | Epic 14; not in first MVP |
| Commercial distribution | deferred (decision closed) | Personal / non-commercial only (CC BY-NC); no commercial-ready claims |
| Wire new stacks into `ui.py` | **pass (W12 follow-up)** | Piper LOCAL TTS toggle + Desktop API listener toggle; CLI `python -m server` |
| Clean mypy on full `tests/` | deferred | Pre-existing debt |

## Hard constraints confirmed

- [x] No commercial-ready claim under CC BY-NC
- [x] Desktop API default bind is loopback; public bind not enabled by gates
- [x] Piper optional engine landed in W12-T01 (not Wave 11); core TTS remains injectable
- [x] Same-LAN bind opt-in landed in W12-T02; wildcards still denied; auth required
- [x] No push / APNs wiring in this wave
- [x] Gate suites do not open live external sockets for cloud providers

## Commands used

```bash
export PY=/Users/slon/mark-worktrees/w01-t03-test-foundation/.venv/bin/python
$PY -m pytest -q
$PY -m ruff check tests
$PY -m mypy   # informational; deferred clean

cd /Users/slon/Documents/GitHub/Slon/ios
export DEVELOPER_DIR=/Users/slon/Downloads/Xcode-beta.app/Contents/Developer
swift test
```
