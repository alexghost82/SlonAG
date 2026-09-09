# WAVE R9 — Observability / Config / Dependencies

**WAVE:** R9  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-020 | `validate_settings` | Dropped `voice_*` | Parser reads voice engines/devices. `to_dict` always emits them. `settings == validate_settings(settings.to_dict())` including custom voice fields. Secrets still rejected. |
| SLON-032 | metrics catalog | Missing | `runtime/metrics.py` counters from the master list. No secrets in snapshot. |
| SLON-031 | health | already present | `/v1/health` + `sanitize_body` remain; tests still pass. |

## REMOVED LEGACY

None.

## TESTS

`python -m pytest tests/unit/config/test_schema.py tests/unit/runtime/test_metrics.py tests/unit/server/routes/test_routes_health.py -q` → **54 passed**

## SECURITY

- Secret-like keys still rejected by `validate_settings`.
- Health/status sanitize body (existing).
- Metrics names are fixed; unknown names rejected.

## MIGRATIONS

- Older `settings.json` without voice keys still loads defaults.

## KNOWN LIMITATIONS

- Production `print()` not globally removed (PARTIAL; high blast radius).
- Lockfile not hand-edited. No new dependency.
- Metrics not yet wired into every AgentLoop/provider call site.

## RUNTIME VERIFICATION STILL REQUIRED

- Vulnerability/license CI audit (R10 if compatible).

## COMMITS

Recorded after commit.
