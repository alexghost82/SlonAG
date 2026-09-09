# WAVE R5 — Event / Jobs / Automation

**WAVE:** R5  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-023 | *(missing Job Engine)* | RAM `TaskQueue` ≠ crash-safe jobs | New `runtime/jobs.py` `JobEngine`: UUID, type, payload, states PENDING/RUNNING/WAITING/RETRYING/PAUSED/COMPLETED/FAILED/CANCELLED, attempts, `next_retry_at`, owner/session, `idempotency_key`, checkpoint, error, result_ref, cancellation. SQLite WAL. Restart recovery of RUNNING. Wired on `RuntimeStack.job_engine`. |
| SLON-024 | `runtime/events.py` | Incomplete bus | Extended **the same** `RuntimeEventBus`: `event_id`, `event_type`, `timestamp`, `source`, `job_id`, `correlation_id`, `schema_version`, optional `payload`, bounded replay history, isolated subscriber failure. New kinds: `job_progress`, `error`, `session_changed`, `approval_required`, `assistant_text`. |
| SLON-037 | three engines | Looked like duplicate job systems | Call-graph: **Job Engine = `runtime.jobs`**. `acta.automation` = scheduler/cron. `acta.proactive` = suggestion filter. `acta.workflow_learning` = template mining. Not deleted (not duplicates of the Job Engine). |

## REMOVED LEGACY

None. `TaskQueue` remains RAM adapter for queued text (R2). Automation JSON store remains for schedules.

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/unit/runtime/test_jobs.py tests/unit/runtime/test_events.py tests/unit/bridge/test_runtime_stack.py -q` | **12 passed** |
| `python -m pytest tests/unit/runtime/test_jobs.py tests/unit/runtime/test_events.py tests/unit/runtime/test_live_components.py tests/unit/proactive tests/unit/workflow_learning tests/unit/automation tests/unit/bridge/test_runtime_stack.py tests/unit/gateway/test_gateway.py -q` | **338 passed**, 1 fail then fixed; rerun jobs/events **12 passed** |

## SECURITY

- Duplicate enqueue blocked by unique `idempotency_key`.
- Terminal states are sticky (no second complete/fail side effect).
- Event sinks still isolated; tool args stay off legacy UI fields.

## MIGRATIONS

- New `memory/slon_jobs.sqlite3` (gitignored via `*.sqlite3`).

## KNOWN LIMITATIONS

- `TaskQueue` is not yet a thin client of JobEngine (queued text still RAM).
- Automation engine still persists schedules as JSON; it does not yet enqueue every fire through JobEngine (PARTIAL wiring).
- Event history is in-process ring, not durable across process death.

## RUNTIME VERIFICATION STILL REQUIRED

- Process-kill during `claim`/`complete` on a real disk.
- DST/missed cron still covered by existing automation tests, not re-proven here against JobEngine.

## COMMITS

Recorded after commit.
