# Runtime Verification Matrix — SlonAG

**Clone:** `/Users/alexandr.bogdanov/Documents/GitHub/ghst/SlonAG`  
**Wave:** R0 baseline (2026-09-09)  
**Rule:** never mark `PASS` without actually running the check. Absence of a run is `NOT_RUN`.

Levels: `STATIC` / `UNIT` / `INTEGRATION` / `E2E` / `HARDWARE` / `MANUAL` / `N/A`.

Result vocabulary: `PASS` / `FAIL` / `NOT_RUN` / `SKIPPED` / `BLOCKED` / `N/A`.

---

## A. Quality-gate commands (this machine, R0)

| ID | Check | Level | Command | Result | Evidence | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| RV-CI-01 | pytest collect | STATIC | `python -m pytest tests --collect-only -q` | PASS | exit 0; **2545** tests; 21.05s | `.venv` CPython 3.12.14 |
| RV-CI-02 | pytest full | UNIT+INTEGRATION+E2E | `python -m pytest tests` | FAIL | 38 failed, 2446 passed, 28 skipped, 33 errors, 198.37s | Clusters: browser Playwright ERROR/FAIL, filesystem security, e2e chain, wave15 offline, MCP streamable HTTP. Honest red baseline. |
| RV-CI-03 | ruff lint | STATIC | `python -m ruff check .` | FAIL | exit 1; **507** errors | F401/I001 dominate; 416 fixable |
| RV-CI-04 | ruff format | STATIC | `python -m ruff format --check .` | FAIL | exit 1; **246** files would reformat | Do not mass-format in R0 |
| RV-CI-05 | mypy | STATIC | `python -m mypy` | FAIL | exit 2; 7 errors / 7 files | yaml, send2trash, mcp, openai×2, faster_whisper, numpy stub vs `python_version = 3.11` |
| RV-CI-06 | GitHub Actions CI | STATIC | read `.github/workflows/ci-release-gate.yml` | N/A | workflow requires pytest+ruff+mypy; hardware gated | Not executed on GitHub from this wave. Local tree would fail ruff/mypy jobs. Do not change branch protection. |

---

## B. P0 defect verification (how each finding must be proven)

| Finding | STATIC | UNIT | INTEGRATION | E2E | HARDWARE | MANUAL | Current result | Next wave |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SLON-001 async parallel gate | PASS — source `execute_many_async` gather | NOT_RUN (no async twin of parallel_safe tests) | N/A | N/A | N/A | N/A | STATIC only | R1 |
| SLON-002 retryable on success | PASS — L361 `retryable=True` | NOT_RUN | N/A | N/A | N/A | N/A | STATIC only | R1 |
| SLON-003 weak registered shell | PASS — `LEGACY_HANDLERS["shell_exec"] is shell_exec_handler` | PARTIAL — e2e patches `create_subprocess_shell` (proves weak path) | NOT_RUN vs hardened | NOT_RUN | N/A | N/A | STATIC + existing e2e coupling | R1 |
| SLON-004 hardened not registered | PASS | Existing tests hit `actions.shell_exec` **directly** — does **not** prove production | N/A | N/A | N/A | N/A | STATIC | R1 |
| SLON-005 `_safe_cwd` prefix | PASS — startswith + is_dir fallback | NOT_RUN `/tmpx`, symlink, foreign HOME | N/A | N/A | N/A | N/A | STATIC | R1 |
| SLON-006 `run_until_complete` | PASS — L800 | NOT_RUN on running loop | N/A | N/A | N/A | N/A | STATIC | R1 |
| SLON-007 `shell=True` | PASS — two action files | NOT_RUN | N/A | N/A | N/A | N/A | STATIC | R1 |
| SLON-008 timeout leftover | PASS — warning string + no cancel class | NOT_RUN hung/child/cancel | N/A | N/A | N/A | N/A | STATIC | R1 |
| SLON-009 liberal memory prompt | PASS — prompt text + or_client | NOT_RUN | N/A | N/A | N/A | N/A | STATIC | R1 |
| SLON-010 TaskQueue AgentExecutor | PASS | NOT_RUN factory injection | NOT_RUN listener submit | N/A | N/A | N/A | STATIC | R2 |
| SLON-011 execute_plan | PASS | Existing tests construct AgentExecutor (legacy allowed) | NOT_RUN | N/A | N/A | N/A | STATIC | R2 |
| SLON-012/013/014/016 SDK bypass | PASS — ripgrep imports | No architecture AST suite (`tests/architecture/` missing) | NOT_RUN | N/A | N/A | N/A | STATIC | R3 |
| SLON-015/022 SlonLive | PASS — `main.py` genai | NOT_RUN | NOT_RUN | NOT_RUN | N/A | NOT_RUN live mic | PARTIAL by decision | R3/R7 |
| SLON-017/018/029 memory dual + DBs | PASS — untracked sqlite; provenance in repository | PASS — `tests/unit/memory` 70 passed; provenance + migrate | NOT_RUN live hardware | N/A | N/A | N/A | UNIT PASS R4; Live hardware NOT_RUN | R10 leftover JSON module |
| SLON-019 gitignore | PASS after R0 edit | N/A | N/A | N/A | N/A | N/A | R0 STATIC fix | R4 untrack |
| SLON-020 voice_* drop | PASS — validate_settings omits fields | NOT_RUN round-trip assert | N/A | N/A | N/A | N/A | STATIC | R9 |
| SLON-021/036 lint exclusions + CI red | PASS — pyproject + local ruff/mypy FAIL | N/A | N/A | N/A | N/A | N/A | STATIC FAIL recorded | R10 |
| SLON-023 Job Engine | PASS — no module | N/A | N/A | N/A | N/A | N/A | SPEC_GAP | R5 |
| SLON-024/025 events + UI plane | PASS — limited event kinds; main owns Live/memory | Existing `tests/unit/runtime/test_events.py` (narrow) | NOT_RUN | N/A | N/A | NOT_RUN UI | PARTIAL | R5/R7 |
| SLON-026 architecture tests | PASS — dir missing | NOT_RUN | N/A | N/A | N/A | N/A | SPEC_GAP | R2/R3 |
| SLON-027 offline socket escape | PARTIAL — NetworkPolicy units exist | NOT_RUN socket/httpx patches | NOT_RUN | N/A | N/A | N/A | PARTIAL | R1 |
| SLON-027/033 MCP FS browser | PASS inventory | Some FS/security tests exist | NOT_RUN full adversarial | NOT_RUN | N/A | N/A | REQUIRES_RUNTIME_TEST | R8 |
| SLON-034 gateway/sessions | PASS inventory | Existing gateway/session units | NOT_RUN reconnect/resume/malformed | N/A | N/A | NOT_RUN iOS LAN | PARTIAL | R6 |
| SLON-038 AgentLoop retry/cancel | PARTIAL — types exist | Some wave15 offline tests | `tests/integration/test_wave15_offline_agent.py` exists; **result = full suite run** | N/A | N/A | N/A | NOT claimed PASS until pytest recorded | R2 |

---

## C. Existing suites (presence ≠ PASS)

These directories exist. R0 does **not** mark them PASS until `python -m pytest tests` finishes and the wave report records passed/failed/skipped.

| Path | Intended level | Presence |
| --- | --- | --- |
| `tests/tools/` | UNIT | present |
| `tests/security/` | UNIT | present |
| `tests/offline/` | UNIT | present |
| `tests/agent/` | UNIT | present |
| `tests/unit/agent/` | UNIT | present |
| `tests/unit/providers/` | UNIT | present |
| `tests/unit/memory/` | UNIT | present |
| `tests/unit/gateway/` | UNIT | present |
| `tests/unit/sessions/` | UNIT | present |
| `tests/unit/runtime/` | UNIT | present |
| `tests/integration/` | INTEGRATION | present |
| `tests/e2e/` | E2E | present |
| `tests/architecture/` | ARCH | **absent** |
| Hardware GPU/RTSP (`-m gpu` / `-m rtsp`) | HARDWARE | workflow gated; **NOT_RUN** on this CPU Mac |

---

## D. Hardware / MANUAL / N/A

| ID | Item | Level | Result | Reason |
| --- | --- | --- | --- | --- |
| RV-HW-01 | GPU tests | HARDWARE | NOT_RUN | No `HW_GPU_AVAILABLE`; CI job skipped by design |
| RV-HW-02 | RTSP tests | HARDWARE | NOT_RUN | Same |
| RV-MAN-01 | Desktop Live voice barge-in | MANUAL | NOT_RUN | Requires mic + Gemini credentials; not invoked in R0 |
| RV-MAN-02 | iOS pairing + pin | MANUAL | NOT_RUN | Sibling `ios/**`; this wave does not drive a device |
| RV-NA-01 | Ghost product | N/A | N/A | Must not be implemented; R11 collision notes only |
| RV-NA-02 | Publish Desktop API to internet | N/A | N/A | Forbidden |

---

## E. Update protocol

After every later wave:

1. Re-run the narrow suite for that wave.
2. After R3, R7, R10, and before R11: full four-command gate.
3. Change a row to `PASS` only with command + exit + counts.
4. If a check cannot run, set `BLOCKED` and a SLON-XXX — never `PASS`.
