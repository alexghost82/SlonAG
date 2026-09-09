# SlonAG Production Readiness Report

**Clone:** `/Users/alexandr.bogdanov/Documents/GitHub/ghst/SlonAG`  
**Branch:** `agent/r0-r11-core-hardening`  
**Date:** 2026-09-09  
**Program:** R0–R11 production remediation  

## Final verdict

**NOT_PRODUCTION_READY**

P0 leftovers remain: Gemini Live is still a second reasoning/transport plane; the full quality gate is red (pytest 17 failed / 33 errors, ruff 512, format 253 files, mypy 8). Documented limitations are not the only blockers.

---

## 1. Executive summary

R0–R11 executed sequentially in this clone with one commit per wave. Core invariants improved: AgentLoop for queued text, provider SDK allowlist, canonical SQLite memory with provenance, JobEngine, Gateway/session tests, typed UI commands, MCP fail-closed, FS symlink fix, voice settings round-trip. The tree is **not** production-ready.

## 2. Scope and method

Work stayed in this clone. No `/Users/slon/...`. No push. No Ghost implementation. No Desktop API published. No `config/api_keys.json` or `memory/*.json` copied. Unrelated user sqlite sidecar deletions were preserved.

## 3. Wave completion

| Wave | SHA | Status |
| --- | --- | --- |
| R0 | `95f2f74` | COMPLETE |
| R1 | `d104c1c` | COMPLETE |
| R2 | `1813960` | COMPLETE |
| R3 | `20c0b1c` | COMPLETE |
| R4 | `006d925` | COMPLETE |
| R5 | `b9eacaf` | COMPLETE |
| R6 | `63589c1` | COMPLETE |
| R7 | `5c24ee3` | COMPLETE (Live transport PARTIAL) |
| R8 | `0db6706` | COMPLETE |
| R9 | `ec02dbf` | COMPLETE |
| R10 | `f310225` | COMPLETE |
| R11 | (this commit) | COMPLETE — qualification only |

## 4. Architecture

Canonical stack remains AgentLoop / ProviderRouter / ToolExecutor / SafetyPolicy. No second architecture was added. Job persistence is `runtime.jobs.JobEngine`. Events extend `runtime.events.RuntimeEventBus` only.

## 5. Runtime / AgentLoop

Queued/text/session/gateway orchestration uses AgentLoop via `RuntimeStack.create_agent_loop()`. Production `AgentExecutor(` constructions are gone (architecture AST). SlonLive / Gemini Live still owns realtime audio. **One AgentLoop = PARTIAL** until a provider-neutral live contract replaces Gemini Live transport.

## 6. Providers / AI plane

SDK imports allowed only in `providers/**` and documented `config/onboard.py`. Text ops use Router + NeverFallbackPolicy. `or_client.py` has no production callers; file kept for tests.

## 7. Tools / Safety / Shell

`execute_many_async` uses the sync parallel gate. Success `retryable=False`. Registered `shell_exec` is hardened `actions.shell_exec`. `_safe_cwd` uses `resolve` + `is_relative_to`. `shell=True` removed from the two named actions.

## 8. Memory / persistence

Canonical store is `acta.memory` SQLite WAL with provenance/scope/TTL. Live path reads/writes the store. ASSISTANT_UNVERIFIED cannot become PERSONAL. Runtime sqlite untracked. JSON `memory_manager` remains for extract gate + fallback.

## 9. Jobs / events / automation

JobEngine: UUID, states, idempotency, crash recovery. Event bus: event_id, catalog, replay ring. Automation = scheduler; proactive = suggestions; workflow_learning = templates. TaskQueue still RAM for text turns.

## 10. Gateway / sessions

Gateway is the remote iOS boundary. `server/*` is local `/v1`. TLS/pairing/Ed25519 not weakened. Session expire/resume/crash/duplicate/cancel tests added. iOS hardware MANUAL. `ios/**` not edited.

## 11. UI / voice

Typed `UiCommand` catalog + control-plane dispatch. UI architecture test forbids AgentLoop/ToolExecutor/Router/Live imports. VoiceBridge exists and is provider-neutral. SlonUI is not fully a thin widget layer. Gemini Live remains in `main.py`.

## 12. MCP / browser / filesystem

MCP CONFIRM cannot auto-approve. Descriptions/output untrusted and bounded. FS security unit suite green after macOS `/var` ancestor-symlink fix. Playwright Chromium missing → browser integration ERROR/FAIL.

## 13. Observability / config / dependencies

`voice_*` round-trip fixed. Metrics catalog exists (not fully wired). Health/status sanitize. Production `print()` not globally removed. Lockfiles not hand-edited.

## 14. CI / cross-platform / cleanup

Staged ruff include: `runtime/jobs.py`, `runtime/metrics.py`, `runtime/commands.py`. Legacy excludes remain. Branch-protection recommendation documented; GitHub admin not changed.

## 15. Quality-gate evidence (R11, this machine)

Interpreter: `.venv/bin/python` CPython 3.12.14.

| Command | Exit | Result |
| --- | --- | --- |
| `python -m pytest tests` | 1 | **17 failed, 2540 passed, 28 skipped, 33 errors** (74.26s) |
| `python -m ruff check .` | 1 | **512 errors** |
| `python -m ruff format --check .` | 1 | **253 files** would reformat |
| `python -m mypy` | 2 | **8 errors / 8 files** (aiohttp, yaml, send2trash, mcp.streamable_http, openai×2, faster_whisper, numpy stub vs `python_version=3.11`) |

R0 baseline was 38 failed / 2446 passed / 33 errors. Filesystem security suite is now green. Remaining red: Playwright missing, e2e chain, wave15 offline agent (2), MCP streamable HTTP (3), listener pairing, some FS/security/actions.

## 16. Security posture

Hardened: shell argv, parallel policy, offline socket escape tests (R1), memory poisoning prefix, MCP approval, FS traversal, Gateway pairing unchanged. Open: e2e path-traversal test still red; Playwright not run; Live path still Gemini-specific.

## 17. Privacy / local_only

Extract/text_ops fail-closed in offline / local_only / fully_local. NeverFallbackPolicy on Router text ops. No hidden cloud fallback added.

## 18. Spec compliance — Wave 14

| Item | Status | Evidence |
| --- | --- | --- |
| Unified ToolSpec / ToolExecutor / SafetyPolicy | IMPLEMENTED | `acta/tools`, R1 tests |
| Local LLM provider adapters | PARTIAL | providers exist; full suite red |
| Duplicate tool paths eliminated | PARTIAL | hardened shell registered; some actions remain |

## 19. Spec compliance — Wave 15

| Item | Status | Evidence |
| --- | --- | --- |
| AgentLoop orchestration | IMPLEMENTED (text/queued) | R2 AST + factory |
| Offline multi-turn agent | CONTRADICTED | `test_offline_agent_*` FAIL |
| Durable jobs | PARTIAL | JobEngine exists; TaskQueue RAM; automation JSON |

## 20. Spec compliance — Post-Wave 15

| Item | Status | Evidence |
| --- | --- | --- |
| One runtime | PARTIAL | AgentLoop + SlonLive |
| One AI plane | IMPLEMENTED (imports) | architecture test |
| One memory | PARTIAL | SQLite canonical; JSON leftover |
| Gateway first-party boundary | IMPLEMENTED (python) | R6 tests; iOS MANUAL |
| Production CI green | MISSING | ruff/mypy/pytest red |

## 21. Ghost readiness (collision points only)

Ghost was **not** implemented. Collision surfaces if Ghost is later integrated:

1. `providers.Router` / model catalog vs Ghost-branded client.
2. ToolRegistry / SafetyPolicy / shell_exec vs Ghost tool names.
3. `acta.memory` provenance vs Ghost memory product.
4. Gateway pairing/TLS vs Ghost remote access.
5. Session engine vs Ghost conversation IDs.
6. Desktop `/v1` listener vs Ghost cloud API (do not publish).
7. UI command catalog vs Ghost chat chrome.
8. Refusal/sanitize layers if Ghost UI strings land in this repo.

## 22. Remaining SLON-XXX

| ID | Severity | Status |
| --- | --- | --- |
| SLON-015/022 | P0 | PARTIAL — Gemini Live transport |
| SLON-017 leftover | P1 | JSON `memory_manager` still present |
| SLON-023 leftover | P1 | TaskQueue not JobEngine client |
| SLON-025 leftover | P1 | UI widgets not fully thin |
| SLON-033 leftover | P1 | Playwright / e2e FS |
| SLON-014 leftover | P2 | `or_client.py` file + tests |
| SLON-021/036 | P1 | Full ruff/mypy/CI red |
| SLON-031 | P2 | `print()` still in production modules |

## 23. Runtime verification still required

- Hardware: mic barge-in, iOS LAN pairing, Playwright Chromium.
- Crash: OS kill during JobEngine WAL write; Live disconnect mid-tool on device.
- E2E chain and Wave 15 offline agent failures (need diagnosis, not skipped).

## 24. Verdict rationale

Required verdict enum: `PRODUCTION_READY` | `PRODUCTION_READY_WITH_DOCUMENTED_LIMITATIONS` | `NOT_PRODUCTION_READY`.

**NOT_PRODUCTION_READY** because at least one P0 remains (dual Live plane) and the mandatory quality gate is red. Documented limitations do not cover failing security/e2e/offline tests or CI lint/typecheck.

Ghost: not implemented. Desktop API: not published. Secrets/memory JSON: not copied.
