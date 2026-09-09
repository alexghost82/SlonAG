# WAVE R0 — Baseline

**WAVE:** R0  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  
**BRANCH:** `agent/r0-r11-core-hardening`  
**BASE:** `88d87d9` (`integration/main`)  
**CLONE:** `/Users/alexandr.bogdanov/Documents/GitHub/ghst/SlonAG`

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-019 (gitignore only) | `.gitignore` | `memory/*.db` did not cover SQLite sidecars or UI memory | Added `*.sqlite3`, `*.sqlite3-wal`, `*.sqlite3-shm`, `memory/gateway_artifacts/`, `ui/memory/` |
| (inventory) | `docs/audit/production-remediation-matrix.md` | No production defect matrix | Created with Status+Evidence for every P0 from the master prompt |
| (inventory) | `docs/audit/runtime-verification-matrix.md` | No verification ledger | Created; PASS only where a command was run |

No runtime/application Python was changed.

## REMOVED LEGACY

None. Tracked `memory/*.sqlite3*` and `ui/memory/*` remain tracked (R4 untrack). User-deleted `memory/slon_sessions.sqlite3-shm` / `-wal` were **not** restored and **not** staged.

## TESTS

| Command | Exit | passed | failed | skipped | errors | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `python -m pytest tests --collect-only -q` | 0 | n/a | n/a | n/a | n/a | 2545 collected / 21.05s |
| `python -m pytest tests` | nonzero | 2446 | 38 | 28 | 33 | 198.37s; 5 warnings |
| `python -m ruff check .` | 1 | — | 507 lint errors | — | — | F401 217, I001 163, F841 37, F811 23, E402 21, F821 13; 416 auto-fixable |
| `python -m ruff format --check .` | 1 | — | 246 files would reformat | — | — | 182 already formatted |
| `python -m mypy` | 2 | — | 7 errors / 7 files | — | — | stubs/missing modules + numpy vs `python_version=3.11` |

Interpreter: `.venv/bin/python` 3.12.14. Dev tools were missing from `.venv` and were installed from `requirements-dev.txt` for this baseline (`pytest 9.1.1`, `ruff 0.16.6`, `mypy 2.3.1`). That install is local tooling, not a repo commit.

Failure clusters (not fixed in R0):

- `tests/integration/test_browser/test_browser_service.py` — many ERROR/FAIL (Playwright/runtime)
- `tests/test_filesystem_security.py` — broad FAIL
- `tests/e2e/test_e2e_chain.py` — filesystem/automation/server/workspace/traversal
- `tests/integration/test_wave15_offline_agent.py` — 2 FAIL
- `tests/security/test_beta_security_gates.py::test_browser_cleanup_on_shutdown`
- `tests/unit/mcp_client/test_streamable_http.py` — 3 FAIL

## SECURITY

- No secrets added. `config/api_keys.json` and `memory/*.json` not copied.
- Gitignore now covers sqlite sidecars; **untrack deferred to R4**.
- P0 shell/network/memory defects confirmed present (see matrix). Not remediated in R0.

## MIGRATIONS

None.

## KNOWN LIMITATIONS

- One AgentLoop is **PARTIAL** until R7 (SlonLive still Gemini Live in `main.py`).
- Dual memory (JSON live path vs `acta/memory` SQLite) remains.
- `tests/architecture/` does not exist.
- `pyproject.toml` still excludes `actions/**`, `agent/**`, `or_client.py`, `memory/**` from ruff/mypy/coverage.
- Local quality gate is red; CI workflow would fail ruff/format/mypy on this tree.
- User uncommitted deletions of sqlite shm/wal preserved.

## RUNTIME VERIFICATION STILL REQUIRED

All rows in `runtime-verification-matrix.md` that are `NOT_RUN` / `REQUIRES_RUNTIME_TEST`, plus hardware GPU/RTSP and MANUAL voice/iOS.

## COMMITS

Recorded after `git commit` in this wave (SHA filled by integrator).

Intended files:

- `.gitignore`
- `docs/audit/production-remediation-matrix.md`
- `docs/audit/runtime-verification-matrix.md`
- `docs/audit/wave-R0-report.md`
