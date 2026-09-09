# WAVE R10 — CI / Cross-platform / Cleanup

**WAVE:** R10  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-021 | ruff include | `runtime/**` not in gate | Staged: `runtime/jobs.py`, `runtime/metrics.py`, `runtime/commands.py` added to ruff include after they passed `ruff check`. Did **not** enable `actions/**`, `agent/**`, `memory/**`, `or_client.py`. Did not expand mypy `ignore_errors`. |
| SLON-036 | CI red | Local ruff/mypy still red repo-wide | Honest: full `ruff check .` remains red (legacy). Staged files are green. |
| SLON-014 leftover | `or_client.py` | File still on disk | Caller proof: no production imports remain (R3). **Kept** because unit tests still import the module. Delete only after those tests migrate. |

## REMOVED LEGACY

None (or_client retained for tests).

## TESTS

| Command | Result |
| --- | --- |
| `ruff check runtime/jobs.py runtime/metrics.py runtime/commands.py` | All checks passed |
| `pytest tests/architecture/test_cross_platform_imports.py -q` | **2 passed** |

## SECURITY

- GitHub admin / branch protection **not** changed.
- Recommendation written to `docs/audit/branch-protection-recommendation.md`.

## MIGRATIONS

None.

## KNOWN LIMITATIONS

- Full repo ruff/format/mypy still fail (R0 baseline).
- `or_client.py` not deleted.
- No lockfile edits. No vulnerability scanner added to CI (would be a new workflow dependency).

## RUNTIME VERIFICATION STILL REQUIRED

- Full suite + ruff + mypy after R10 (required before R11).

## COMMITS

Recorded after commit.
