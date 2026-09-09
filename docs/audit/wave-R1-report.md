# WAVE R1 — Security / correctness

**WAVE:** R1  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  
**BRANCH:** `agent/r0-r11-core-hardening`

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-001 | `ToolExecutor.execute_many_async` | `asyncio.gather` without parallel gate | Same `_calls_are_parallel_safe` as sync (`parallel_safe && read_only && idempotent && !side_effects && independent`) |
| SLON-002 | `execute_async` retryable | Success always `retryable=True` | Success → False; fail only if idempotent **and** transient (`ConnectionError`/`TimeoutError`/`timeout`) |
| SLON-003/004 | `LEGACY_HANDLERS["shell_exec"]` | Weak `create_subprocess_shell` registered | Handler delegates to `actions.shell_exec.shell_exec`; maps legacy `cmd` |
| SLON-005 | `_safe_cwd` | `startswith` + any existing dir | `Path.resolve()` + `is_relative_to(approved_roots)` (home, `/tmp`, `gettempdir()`) |
| SLON-006 | `shell_exec` / `execute_async` | `run_until_complete` on running loop | Banned; sync handlers run via `asyncio.to_thread` |
| SLON-007 | `dev_agent` / `computer_settings` | `shell=True` | Argv `Popen`; Linux brightness via parsed `xrandr` |
| SLON-008/028 | timeout / `CancellationClass` | Hang after timeout; bool only | `cooperative\|killable\|unsafe`; `timed_out=True`; bounded `_drain_after_timeout` |
| SLON-009 | `memory_manager` | Liberal extract as instructions | Conservative prompt; retrieval marked UNTRUSTED DATA; fail-closed offline/local_only/fully_local |
| SLON-027 | `tests/offline` | No socket-level harness | Patch `socket`/`requests`/`httpx`/`aiohttp`; non-loopback FAIL |

## REMOVED LEGACY

- Production `asyncio.create_subprocess_shell` shell_exec handler (function removed, not registered).
- `shell=True` in `actions/dev_agent.py` and `actions/computer_settings.py`.
- Liberal memory extract wording (“Extract ALL / Be LIBERAL”).

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/tools/test_executor.py tests/tools/test_shell_exec.py tests/tools/test_shell_exec_production.py tests/security/test_shell_exec_adversarial.py tests/security/test_memory_trust_boundary.py tests/offline/test_adversarial_network_escape.py tests/tools/test_builtin_registry.py tests/tools/test_legacy_adapters.py tests/e2e/test_e2e_chain.py::TestShellTool tests/e2e/test_e2e_chain.py::TestCancelShell tests/offline/test_network_offline.py tests/offline/test_beta_offline_gates.py -q` | **117 passed** |
| `python -m pytest tests/tools tests/security tests/offline -q` | **421 passed, 1 skipped, 1 failed** (`test_browser_cleanup_on_shutdown` — Playwright Chromium missing; **pre-existing R0**, not this wave) |

## SECURITY

- Registered `shell_exec` is now the hardened argv path.
- Cwd prefix escapes (`/tmpx`, symlink to `/etc`, foreign HOME) rejected.
- Offline memory extract does not call `or_client`.
- `or_client` and action SDK imports still exist (R3). Adversarial harness does not weaken if `main.py` Live later escapes — SLON-015 remains.

## MIGRATIONS

None.

## KNOWN LIMITATIONS

- `or_client` still imported by memory when cloud is allowed (R3 must route through Router).
- `shell_exec` still self-authorizes in addition to ToolExecutor (double gate; fail-closed).
- `_run_subprocess_async` remains unused in the public handler (sync-only after R1).
- Browser cleanup test still red without Chromium (R0 baseline).

## RUNTIME VERIFICATION STILL REQUIRED

MANUAL live voice; HARDWARE GPU/RTSP; full `pytest tests` (R0: 38 fail / 33 error — not claimed fixed).

## COMMITS

Filled after commit.
