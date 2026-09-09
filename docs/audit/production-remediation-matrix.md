# Production Remediation Matrix — SlonAG

**Clone:** `/Users/alexandr.bogdanov/Documents/GitHub/ghst/SlonAG`  
**Branch:** `agent/r0-r11-core-hardening`  
**Base HEAD at R0 start:** `88d87d9` (`integration/main`)  
**Wave:** R0 baseline (2026-09-09)  
**Status vocabulary:** `VERIFIED_PRESENT` / `ALREADY_FIXED` / `PARTIAL` / `SPEC_GAP` / `OBSOLETE` / `REQUIRES_RUNTIME_TEST`

Columns: ID, Severity, Subsystem, File, Symbol, Status, Evidence, Root Cause, Required Fix, Dependencies, Acceptance Test, Runtime Verification, Completion Status.

Do **not** mark Completion Status `DONE` until the owning wave DoD is met.

**Wave progress:** R0 `95f2f74`. R1 `d104c1c`. R2 `1813960`. R3 `20c0b1c`. R4 `006d925`. R5 in progress — JobEngine + extended RuntimeEventBus. SlonLive still Gemini transport until R7.

---

## Status legend

| Status | Meaning |
| --- | --- |
| VERIFIED_PRESENT | Defect confirmed in this clone by source inspection |
| ALREADY_FIXED | Required behavior already present on the production path |
| PARTIAL | Some pieces exist; required invariant is not closed |
| SPEC_GAP | Spec requires it; no production implementation found |
| OBSOLETE | Finding no longer applies (caller gone or replaced) |
| REQUIRES_RUNTIME_TEST | Static evidence exists; PASS/FAIL needs a live run |

---

## CI baseline (R0, recorded)

Interpreter: `.venv/bin/python` → CPython 3.12.14. Dev tools installed from `requirements-dev.txt` for this baseline (`pytest 9.1.1`, `ruff 0.16.6`, `mypy 2.3.1`). They were **not** present in `.venv` before R0.

| Command | Exit | Result |
| --- | --- | --- |
| `python -m pytest tests --collect-only -q` | 0 | **2545 tests collected** in 21.05s |
| `python -m pytest tests` | 1 (nonzero; tee wrapper printed 0) | **38 failed, 2446 passed, 28 skipped, 5 warnings, 33 errors** in 198.37s |
| `python -m ruff check .` | 1 | **507 errors** (416 auto-fixable). Top: F401 217, I001 163, F841 37, F811 23, E402 21, F821 13 |
| `python -m ruff format --check .` | 1 | **246 files would be reformatted**, 182 already formatted |
| `python -m mypy` | 2 | **7 errors / 7 files** (yaml stubs, send2trash stubs, mcp.client.streamable_http, openai×2, faster_whisper, numpy stub vs `python_version=3.11`) |

`pyproject.toml` still excludes `actions/**`, `agent/**`, `or_client.py`, `memory/**` from ruff/mypy/coverage. Those modules are **not** in this baseline gate. Staged enablement is R10.

Working tree at R0 start (preserved, not restored): user-deleted `memory/slon_sessions.sqlite3-shm` and `memory/slon_sessions.sqlite3-wal`. Not committed in R0.

---

## P0 findings (master prompt — re-verified)

| ID | Severity | Subsystem | File | Symbol | Status | Evidence | Root Cause | Required Fix | Dependencies | Acceptance Test | Runtime Verification | Completion Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SLON-001 | P0 | Tools | `acta/tools/executor.py` | `ToolExecutor.execute_many_async` | VERIFIED_PRESENT | L365–396: `asyncio.gather` over every call. Sync `execute_many` (L180–195) gates on `parallel_safe && read_only && idempotent && !side_effects && independent`. Async path has **no** gate. | Async batch added for MCP without copying sync policy. | Use the same predicate; otherwise sequential `execute_async`. | SLON-002 | `tests/tools/test_executor.py` async twin of `test_execute_many_parallel_safe_*` | UNIT | OPEN — R1 |
| SLON-002 | P0 | Tools | `acta/tools/executor.py` | `ToolExecutor.execute_async` | VERIFIED_PRESENT | L355–361: success path `replace(..., retryable=True)` unconditionally. Contrast sync handler failure: `retryable=outcome.retryable and spec.idempotent` (L149). | Async normalize overwrites retry semantics. | Success → `retryable=False`. Fail → `spec.idempotent` **and** transient error. Never auto-retry side-effecting non-idempotent ops. | SLON-001 | Regression on production `execute_async` success + non-idempotent failure | UNIT | OPEN — R1 |
| SLON-003 | P0 | Tools/Shell | `acta/tools/legacy/adapters.py` | `shell_exec_handler` / `LEGACY_HANDLERS["shell_exec"]` | VERIFIED_PRESENT | L207–278 `asyncio.create_subprocess_shell`; L623 registers it. `acta/tools/builtin.py` binds registry to `LEGACY_HANDLERS`. E2E `tests/e2e/test_e2e_chain.py` patches `create_subprocess_shell`. | Wave 22 registered a weak async wrapper instead of hardened argv executor. | Register hardened `actions/shell_exec.py` as the production handler. Remove `create_subprocess_shell` from production path. | SLON-004, SLON-005, SLON-006 | Production-path tests via `LEGACY_HANDLERS["shell_exec"]` / ToolExecutor, not only `actions.shell_exec` direct import | UNIT + INTEGRATION | OPEN — R1 |
| SLON-004 | P0 | Tools/Shell | `actions/shell_exec.py` | `shell_exec` | VERIFIED_PRESENT | Hardened module exists; `tests/tools/test_shell_exec.py` imports `actions.shell_exec` directly. Not in `LEGACY_HANDLERS`. | Replacement never wired. | Same as SLON-003. Do not delete weak handler until callers + tests migrate. | SLON-003 | Registry identity: `spec.handler` is hardened wrapper | UNIT | OPEN — R1 |
| SLON-005 | P0 | Tools/Shell | `actions/shell_exec.py` | `_safe_cwd` | VERIFIED_PRESENT | L329–351: `str(path).startswith(str(home))` and `startswith("/tmp")`; fallback `if path.is_dir(): return path` (any existing dir). Prefix match allows `/tmpx` and `/Users/meevil`. | String prefix + existence fallback. | `Path.resolve()` + `is_relative_to(approved_roots)`. No startswith. No “any existing dir”. | SLON-003 | Adversarial: `/tmpx`, foreign HOME, symlink escape, `../` | UNIT | OPEN — R1 |
| SLON-006 | P0 | Tools/Shell | `actions/shell_exec.py` | `shell_exec` | VERIFIED_PRESENT | L796–806: `loop = asyncio.get_running_loop()` then `loop.run_until_complete(...)` — illegal on a running loop; will raise or deadlock. | Sync handler called from async executor without `to_thread`. | Ban `run_until_complete` inside a running loop. Sync handlers must not block the asyncio loop (`asyncio.to_thread` or sync-only path). | SLON-003, SLON-028 | Call registered handler from `execute_async`; must not raise `RuntimeError: this event loop is already running` | UNIT | OPEN — R1 |
| SLON-007 | P0 | Tools/Shell | `actions/dev_agent.py`, `actions/computer_settings.py` | `subprocess.*(..., shell=True)` | VERIFIED_PRESENT | `dev_agent.py:285`; `computer_settings.py:127,156`. Tests forbid `shell=True` in other actions (`test_reminder.py`, `test_beta_security_gates.py`) but these two remain. | Legacy convenience. | Route through the same argv executor / drop `shell=True`. | SLON-003 | Source + runtime: no production `shell=True` | UNIT | OPEN — R1 |
| SLON-008 | P0 | Tools | `acta/tools/executor.py`, `actions/shell_exec.py` | timeout / `communicate` | VERIFIED_PRESENT | Executor timeout warning: “already running legacy operation may continue” (L122–125, L326–328). `ToolSpec` has `cancellable: bool` only — no `cooperative\|killable\|unsafe` class. Timeout + `kill_tree=False` can hang on `communicate()`. | Missing cancellation class; leftover process after timeout. | Add cancellation class if needed. `timed_out=True`. `communicate()` after timeout must not hang when `kill_tree=False`. Classify leftover handlers. | SLON-028 | Hung process, child after timeout, cancel mid-exec | UNIT | OPEN — R1 |
| SLON-009 | P0 | Memory | `memory/memory_manager.py` | `extract_memory` / `should_extract_memory` | VERIFIED_PRESENT | L178–194: “Extract ALL… Be LIBERAL: if something MIGHT be worth remembering”. Calls `or_client.client` (L146, L173). `main.py` L13–16 imports these into the live path. | Retrieval treated as instructions; liberal extraction + SDK bypass. | Remove liberal prompt. Retrieved memory is DATA not instructions. Extract via Router or no-op in `local_only`. | SLON-014, SLON-017 | Prompt text gone; local_only no cloud extract | UNIT + OFFLINE | OPEN — R1 (prompt/trust) / R3–R4 (routing + store) |
| SLON-010 | P0 | Runtime | `agent/task_queue.py` | `TaskQueue._get_executor` / `_run_task` | VERIFIED_PRESENT | L53–57 constructs `AgentExecutor()`. `_run_task` L181–186 calls `executor.execute(...)`. Entries: `agent_task_handler` (`adapters.py:185`), `server/listener.py:825`. | Legacy queue never switched to `RuntimeStack.create_agent_loop()`. | `_run_task` must create `AgentLoop` via factory. After R2: zero production `AgentExecutor(` constructions. | SLON-011, SLON-026 | AST scan + queue unit test uses AgentLoop | UNIT + ARCH | OPEN — R2 |
| SLON-011 | P0 | Runtime | `agent/executor.py` | `execute_plan` / `AgentExecutor` | VERIFIED_PRESENT | `execute_plan` L410–417: `AgentExecutor()`. Gemini helpers `_detect_language` / `_translate_to_goal_language` / `_summarize` import `google.generativeai` (L80, L99, L367). | Dual orchestration: plan executor vs AgentLoop. | Delegate to AgentLoop or unused in production. Do not delete planner files until callers gone. | SLON-010, SLON-012, SLON-013 | Architecture AST fail on production `AgentExecutor(` | ARCH | OPEN — R2 / R3 |
| SLON-012 | P0 | Providers | `agent/planner.py`, `agent/error_handler.py` | plan / replan | VERIFIED_PRESENT | Both import `google.generativeai` (planner L85/L155; error_handler L88/L158). | Direct SDK, not Router. | Route through `providers.Router` or fail-closed in `local_only`. | SLON-013, SLON-016 | `tests/architecture/test_provider_imports.py` | ARCH + UNIT | OPEN — R3 |
| SLON-013 | P0 | Providers | `agent/executor.py` | `_detect_language`, `_translate_to_goal_language`, `_summarize` | VERIFIED_PRESENT | Direct `google.generativeai` as above. | Language/summary ops outside AI plane. | New Router contracts if needed; no SDK outside `providers/**`. | SLON-012 | Same architecture test | ARCH | OPEN — R3 |
| SLON-014 | P0 | Providers | `or_client.py` + callers | `client.chat` | VERIFIED_PRESENT | Production callers: `memory/memory_manager.py`, `actions/computer_settings.py`, `actions/youtube_video.py`, `actions/web_search.py`, `actions/flight_finder.py`. | Parallel OpenRouter client beside Router. | Remove or route through Router. NeverFallback / local_only. No hidden cloud. | SLON-009, SLON-016 | Import scan + local_only fail-closed | ARCH + OFFLINE | OPEN — R3 |
| SLON-015 | P0 | Providers / Voice | `main.py` | Gemini Live `genai.Client` | VERIFIED_PRESENT | `from google import genai` / `from google.genai import types` at L9–10. Live `voice_config` ~L345. Architecture decision: SlonLive remains realtime transport until R7. | Live session constructed in app entry, not `providers/gemini`. | R3: move Client setup behind `providers/gemini`. R7: VoiceBridge; AgentLoop must not depend on Gemini Live. Document One AgentLoop as **PARTIAL** until R7. | SLON-022 | Architecture allowlist + live smoke | ARCH + MANUAL | OPEN — R3 (move) / R7 (contract) |
| SLON-016 | P0 | Providers | `actions/*.py` | SDK imports | VERIFIED_PRESENT | `file_processor.py`, `dev_agent.py`, `code_helper.py`, `screen_processor.py` import `google.generativeai` / `google.genai`. | Actions call vendors directly. | Router or fail-closed. If too large: SLON-XXX PARTIAL + fail-closed in `local_only`, not silent cloud. | SLON-012, SLON-014 | Architecture test allowlist: SDK only in `providers/**` (+ documented onboard) | ARCH | OPEN — R3 |
| SLON-017 | P0 | Memory | `memory/memory_manager.py` vs `acta/memory/*` | dual stores | PARTIAL | Live read/write now uses `RuntimeStack.memory` (`format_store_for_prompt` / `commit_extracted_facts`). JSON file remains for extract gate + empty-stack fallback. `selfimprovement` may still import JSON manager. | Two architectures. | One canonical memory: personal / session / working context. Provenance enum. Migrate JSON. Wire live path off legacy once replacement covers extraction. | SLON-009, SLON-018, SLON-029 | Migration + live-path unit | UNIT | DONE (Live path) — leftover JSON module R10 |
| SLON-018 | P0 | Hygiene | `memory/slon_sessions.sqlite3*`, `ui/memory/slon_sessions.sqlite3*` | tracked runtime DBs | ALREADY_FIXED | R4 `git rm --cached` of six runtime SQLite files. Fixtures kept. | Runtime DBs committed. | Untrack after gitignore (R4). Do not delete fixtures (`tests/unit/memory/fixtures/legacy_memory.json` is JSON, keep). | SLON-019 | `git ls-files` has no runtime sqlite | STATIC | DONE — R4 |
| SLON-019 | P0 | Hygiene | `.gitignore` | sqlite patterns | ALREADY_FIXED | Pre-R0: `memory/*.db` only. Missing `*.sqlite3`, `-wal`, `-shm`, `memory/gateway_artifacts/`, `ui/memory/`. | Incomplete ignore. | Add patterns in R0. Do not `git rm` tracked DBs in R0. | SLON-018 | gitignore contains patterns | STATIC | DONE — R0 ignore + R4 untrack |
| SLON-020 | P0 | Config | `config/schema.py` | `validate_settings` | VERIFIED_PRESENT | `Settings` has `voice_*` (L179–182). `to_dict` emits them. `validate_settings` L253–265 constructs `Settings(...)` **without** voice fields → dropped on round-trip. | Parser never wired voice keys. | `settings == validate_settings(settings.to_dict())` for all persisted fields. | — | `tests/unit/config/test_schema.py` round-trip | UNIT | OPEN — R9 |
| SLON-021 | P1 | CI | `pyproject.toml` | ruff/mypy/coverage omit | VERIFIED_PRESENT | exclude `actions/**`, `agent/**`, `or_client.py`, `memory/**`. | Legacy debt hidden from gate. | Staged enable after each module is clean (R10). Do not enable all at once. | R1–R9 module cleanup | Gate includes cleaned modules | STATIC | OPEN — R10 |
| SLON-022 | P0 | Runtime / Voice | `main.py`, `runtime/live_session.py` | SlonLive / Gemini Live | PARTIAL | AgentLoop exists (`agent/runtime.py`) and is used by `acta/bridge.RuntimeStack.create_agent_loop`, `sessions/binding.py`, `main._run_chat_agent`. Live audio still Gemini-specific. | Two reasoning/transport planes. | Do **not** claim “One AgentLoop DONE” while SlonLive still reasons. VoiceBridge / provider-neutral live contract in R7. | SLON-015, SLON-025 | Voice interrupt/barge-in tests | E2E + MANUAL | OPEN — R7 |
| SLON-023 | P0 | Jobs | `runtime/jobs.py` | `JobEngine` | ALREADY_FIXED | SQLite WAL Job Engine with required fields/states; `RuntimeStack.job_engine` recovers RUNNING on start. TaskQueue remains RAM for text turns. | Wave 15 queue ≠ crash-safe jobs. | Canonical Job Engine in R5. Do not build it in R2. | SLON-010, SLON-024 | Restart/recovery tests | UNIT | DONE — R5 (TaskQueue adapter leftover) |
| SLON-024 | P0 | Events | `runtime/events.py` | `RuntimeEventBus` | PARTIAL | Same bus now has `event_id`, catalog kinds, `job_id`, `correlation_id`, `schema_version`, replay ring, isolated sinks. History is not process-durable. | First-cut bus, not the R5/R7 contract. | **Extend** this bus. Do not create a second bus. | SLON-023, SLON-025 | Ordering / subscriber failure / replay tests | UNIT | DONE core — R5; UI command catalog R7 |
| SLON-025 | P0 | UI | `main.py`, `ui.py`, `ui/*` | desktop glue | PARTIAL | `main.py` owns Live client, memory extract, AgentLoop start. UI widgets not proven thin (Commands → Control Plane → Core). | Historical monolith. | Typed commands/events. SlonUI/JarvisUI thin clients. UI must not call providers / ToolExecutor / AgentLoop directly. | SLON-022, SLON-024 | Architecture import scan of `ui/` | ARCH + MANUAL | OPEN — R7 |
| SLON-026 | P0 | Architecture tests | `tests/architecture/` | missing | SPEC_GAP | Directory does not exist. Some executor tests monkeypatch Gemini to Boom, but no repo-wide AST fail on `AgentExecutor(` or vendor SDK imports. | Never added. | R2: AST fail on production `AgentExecutor(`. R3: SDK allowlist. Tests may import legacy explicitly. | SLON-010, SLON-012 | `pytest tests/architecture` | ARCH | OPEN — R2 / R3 |
| SLON-027 | P0 | Security / Offline | `tests/offline/*` | network escape | PARTIAL | Offline tests cover `NetworkPolicy` deny of cloud providers. No adversarial patch of `socket.create_connection` / `requests` / `httpx` / `aiohttp` failing any non-loopback connect under offline / fully_local / local_only. | Policy unit ≠ socket-level escape. | Add adversarial offline tests. If escape needs `main.py`, add finding and fix in R3 — do not weaken the test. | SLON-014, SLON-016 | FAIL on non-loopback connect | OFFLINE | OPEN — R1 |
| SLON-028 | P1 | Tools | `acta/tools/contracts.py` | `ToolSpec.cancellable` | PARTIAL | Bool flag only. No `cooperative \| killable \| unsafe`. | Incomplete contract. | Add cancellation class if required to classify leftover handlers. | SLON-008 | Timeout classification tests | UNIT | OPEN — R1 |
| SLON-029 | P0 | Memory | `acta/memory/repository.py` | `MemoryRecord` | ALREADY_FIXED | Provenance enum + scope + TTL + supersession persisted in `metadata`. `can_promote_to_personal` rejects unverified/inferred/tool-obs. Context prefix is UNTRUSTED DATA. | Propose/commit store is v2 scoping, not full provenance model. | Add provenance; ASSISTANT_UNVERIFIED must not auto-promote to trusted personal fact. | SLON-017, SLON-009 | Unit: unverified cannot become trusted | UNIT | DONE — R4 |
| SLON-030 | P1 | iOS | `ios/**` | sibling tree | ALREADY_FIXED (boundary) | iOS tree present (`ios/MarkRemote`, `ios/Package.swift`). R7: do not edit `ios/**` except if sibling agent blocked. Do not delete. | Ownership split. | Integrate notes only. Ghost not implemented (R11 collision report only). | — | N/A this clone’s Python waves | N/A | OPEN — sibling / R11 notes |

---

## Additional findings discovered in R0

| ID | Severity | Subsystem | File | Symbol | Status | Evidence | Root Cause | Required Fix | Dependencies | Acceptance Test | Runtime Verification | Completion Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SLON-031 | P1 | Hygiene | `agent/task_queue.py` et al. | `print(` | VERIFIED_PRESENT | TaskQueue, planner, error_handler, executor, memory_manager use `print` for control-plane logs. | Pre-observability. | Structured logging + correlation_id (R9). | SLON-032 | No production `print(` on hot paths | STATIC | OPEN — R9 |
| SLON-032 | P1 | Observability | metrics / health | missing catalog | SPEC_GAP | No unified `agent_requests_total`, `tool_timeouts`, `gateway_auth_failures`, etc. | Not implemented. | R9 metrics + health/readiness (no secrets). | SLON-031 | Unit + /health contract | UNIT | OPEN — R9 |
| SLON-033 | P1 | MCP / FS / Browser | `acta/mcp`, `acta/filesystem`, browser actions | policy bypass risk | REQUIRES_RUNTIME_TEST | MCP + filesystem modules exist. Hardened FS layer used by some adapters (`read_file` → `filesystem_operation`). Browser/OS control still legacy actions. Web content trust not proven. | Incremental Wave 14 adapters. | R8 audit: MCP cannot bypass SafetyPolicy; FS `resolve+is_relative_to`; browser content UNTRUSTED. | SLON-003, SLON-005 | Adversarial FS + MCP + injection tests | UNIT + INTEGRATION | OPEN — R8 |
| SLON-034 | P1 | Gateway / Sessions | `gateway/*`, `sessions/*`, `server/*` | dual API | PARTIAL | Gateway has pairing, Ed25519, rate limit, WebSocket backpressure. `server/listener.py` still submits `agent_task`. Session binding uses AgentLoop. Crash/resume/duplicate-event suite not fully proven here. | Legacy `/v1` + first-party gateway. | R6: clarify boundaries; do not weaken TLS/pairing. Session survives disconnect. | SLON-010, SLON-023 | Reconnect / resume / malformed frames | INTEGRATION | OPEN — R6 |
| SLON-035 | P2 | CI | `config/onboard.py` | `from openai import OpenAI` | VERIFIED_PRESENT | mypy + source: onboard wizard imports OpenAI. Allowed in R3 only if wizard-only and tested. | Onboard convenience. | Document allowlist + test; or move behind providers. | SLON-016 | Architecture allowlist | ARCH | OPEN — R3 |
| SLON-036 | P2 | CI | `.github/workflows/ci-release-gate.yml` | mypy job | VERIFIED_PRESENT | Required pytest/ruff/mypy on 3.11+3.12. Hardware job gated. No continue-on-error. Current clone is **red** on ruff/format/mypy vs this workflow. | Local tree drifted from format/lint. | R10 staged cleanup. Do not fake-green. Do not change GitHub admin/branch protection (document only). | SLON-021 | CI green after R10 | STATIC | OPEN — R10 |
| SLON-037 | P1 | Automation | `acta/proactive`, `acta/automation`, `acta/workflow_learning` | three engines | PARTIAL | Call-graph: JobEngine=`runtime.jobs`; automation=scheduler; proactive=suggestions; workflow_learning=templates. Not deleted (not duplicate job queues). Automation does not yet enqueue every fire through JobEngine. | Parallel feature waves. | R5: call-graph; pick ONE canonical implementation; migrate; then remove duplicates. | SLON-023 | Schedule/DST/restart/dedup tests | UNIT | DONE inventory — R5; enqueue wiring leftover |
| SLON-038 | P0 | Runtime | `tests/architecture` AgentLoop invariants | retry/cancel/observation | PARTIAL | AgentLoop + Observation + LoopBudget exist. Explicit retry budget + backoff, `tool_call_count = actual calls`, cancel→executor, partial tool failure as Observation — not fully proven as production invariants. | Wave 15 first cut. | Close in R2 without building Job Engine. | SLON-010 | AgentLoop unit/integration | UNIT | OPEN — R2 |

---

## One AgentLoop status (architecture decision)

**PARTIAL until R7.** Canonical queued/text/session/gateway path should be AgentLoop (`agent/runtime.py` via `RuntimeStack.create_agent_loop`). Verified AgentLoop callers: `acta/bridge/__init__.py`, `sessions/binding.py`, `main._run_chat_agent`, `gateway` via session stack.

**Exceptions still present:**

1. `TaskQueue` → `AgentExecutor.execute()` (SLON-010) — R2.
2. `execute_plan` → `AgentExecutor()` (SLON-011) — R2.
3. SlonLive / Gemini Live still the realtime audio transport and still constructed in `main.py` (SLON-015, SLON-022) — remain until R7 VoiceBridge.

Do not claim “One AgentLoop DONE” before R7.

---

## Canonical planes (do not reopen)

| Plane | Canonical | Illegal parallel architecture |
| --- | --- | --- |
| Orchestration | `AgentLoop` | New agent framework; keep `AgentExecutor` only until R2 migration |
| AI | `providers.Router` / `ProviderRouter` | `or_client`, raw `google.*` / `openai` / `anthropic` outside `providers/**` |
| Tools | `ToolRegistry` → `SafetyPolicy` → Approval → `ToolExecutor` | Unregistered `create_subprocess_shell` / `shell=True` |
| Events | `runtime/events.py` `RuntimeEventBus` | Second bus |
| Memory (target) | `acta/memory` SQLite + provenance | Live JSON `memory_manager` after R4 |
| Jobs (target) | persistent Job Engine (R5) | RAM `TaskQueue` as source of truth |
| Remote security | `gateway/*` for first-party iOS | Publishing Desktop API to the internet |

Ghost: **do not implement**. R11 report collision points only.

---

## Appendix A — Call graph (production)

```text
Desktop UI (SlonUI / JarvisUI)
  └─ main.py
       ├─ google.genai Client + types.VoiceConfig          [SLON-015 / SlonLive]
       ├─ memory.memory_manager load/update/extract        [SLON-009, SLON-017]
       ├─ _run_chat_agent → RuntimeStack.create_agent_loop → AgentLoop
       └─ (legacy) actions/* SDK / or_client               [SLON-014, SLON-016]

iOS (sibling, ios/** — do not edit in these waves)
  └─ TLS / pairing / pin → gateway/*
       ├─ GatewayAuthService (Ed25519, pairing, rate limit)
       ├─ GatewayWebSocketRuntime
       └─ sessions.SessionAgentBinding
            └─ RuntimeStack.create_agent_loop → AgentLoop
                 ├─ providers.Router
                 └─ ToolExecutor
                      ├─ SafetyPolicy.authorize
                      ├─ execute / execute_async / execute_many[_async]
                      └─ ToolRegistry ← acta.tools.builtin ← LEGACY_HANDLERS
                           ├─ shell_exec → shell_exec_handler (create_subprocess_shell)  [SLON-003]
                           └─ agent_task → agent.task_queue.TaskQueue
                                └─ AgentExecutor.execute()                               [SLON-010]
                                     ├─ agent.planner (google.generativeai)              [SLON-012]
                                     └─ agent.error_handler (google.generativeai)

server/listener.py  (legacy local desktop /v1)
  └─ tool_name="agent_task" → same TaskQueue path         [SLON-034]

Hardened actions/shell_exec.py
  └─ tests import directly; NOT registered                [SLON-004]

acta/memory (SQLite propose/commit)
  └─ not the live main.py path                            [SLON-017]

runtime/events.RuntimeEventBus
  └─ payload-free kinds; subscribed from main.py          [SLON-024]

acta/proactive | acta/automation | acta/workflow_learning
  └─ overlapping automation; no persistent Job Engine     [SLON-023, SLON-037]
```

### AgentLoop vs AgentExecutor construction (production)

| Construction | File:symbol | Production? |
| --- | --- | --- |
| `AgentLoop(...)` | `acta/bridge/RuntimeStack.create_agent_loop` | Yes — canonical factory |
| `AgentLoop(...)` | `agent/runtime.py` (class) | Yes |
| `AgentLoop(...)` | `agent/executor.execute_agent_loop` | Helper; used if callers pass provider/tools |
| `AgentLoop(...)` | `agent/subagent.py`, `agent/memory.py` | Supporting |
| `AgentExecutor()` | `agent/task_queue.py:_get_executor` | **Yes — illegal after R2** |
| `AgentExecutor()` | `agent/executor.py:execute_plan` | **Yes if anyone calls execute_plan** |
| `AgentExecutor(` | `tests/unit/agent/*`, `tests/agent/*` | Tests only — allowed |

### Provider SDK imports (production)

| Module | Import | Wave |
| --- | --- | --- |
| `providers/**` | allowed | canonical |
| `main.py` | `google.genai` | R3 move / R7 contract |
| `config/onboard.py` | `openai` | R3 allowlist or move |
| `agent/planner.py`, `agent/error_handler.py`, `agent/executor.py` | `google.generativeai` | R3 |
| `actions/file_processor.py`, `dev_agent.py`, `code_helper.py`, `screen_processor.py` | `google.generativeai` / `google.genai` | R3 |
| `or_client.py` + memory/actions callers | OpenRouter client | R3 |
| `providers/openai_compat.py` | `openai` | allowed (providers) |

---

## Appendix B — Wave ownership (do not overlap shared files inside a wave)

| Wave | Shared-file owner if touched | Notes |
| --- | --- | --- |
| R0 | `.gitignore` only (app code otherwise unchanged) | docs/audit/* |
| R1 | none of the shared list unless policies need a new file | executor/adapters/shell/memory prompt |
| R2 | not `providers/contracts.py` | task_queue, executor, adapters agent_task, listener submit, bridge |
| R3 | `providers/router.py`; `contracts.py` only if new op; `main.py` only Live move | single owner |
| R4 | memory stack; `main.py` live memory wire | after R3 |
| R5 | `runtime/events.py` extend | no second bus |
| R6 | gateway/sessions; `server/schemas.py` only if required | do not weaken auth |
| R7 | `ui.py` / `main.py` command plane | no `ios/**` |
| R8 | tools/FS/MCP | |
| R9 | `config/schema.py` | voice_* round-trip |
| R10 | `pyproject.toml`, `requirements*.txt` | staged lint enable |
| R11 | docs only | readiness report |

---

## Appendix C — Tracked runtime DBs (do not git-rm in R0)

```text
memory/slon_sessions.sqlite3
memory/slon_sessions.sqlite3-shm   # deleted in this working tree by user; do not restore
memory/slon_sessions.sqlite3-wal   # deleted in this working tree by user; do not restore
ui/memory/slon_sessions.sqlite3
ui/memory/slon_sessions.sqlite3-shm
ui/memory/slon_sessions.sqlite3-wal
```

Untrack in R4 after gitignore (this wave). Keep `tests/unit/memory/fixtures/legacy_memory.json`.
