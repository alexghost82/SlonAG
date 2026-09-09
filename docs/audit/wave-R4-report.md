# WAVE R4 — Memory / Persistence

**WAVE:** R4  
**STATUS:** COMPLETE  
**DATE:** 2026-09-09  
**BRANCH:** `agent/r0-r11-core-hardening`

## FIXED

| ID | File / symbol | Root cause | Implementation |
| --- | --- | --- | --- |
| SLON-017 | `main.py` live path vs `memory_manager` | Dual JSON + SQLite stores; Live read/write used JSON | Live prompt uses `format_store_for_prompt(runtime_stack.memory)`. Extract commits via `commit_extracted_facts` as working/`ASSISTANT_UNVERIFIED`. JSON `update_memory` no longer on the Live write path. `build_runtime_stack` migrates `memory/long_term.json` once into empty SQLite. |
| SLON-018 | tracked `memory/*.sqlite3*` / `ui/memory/*` | Runtime DBs committed | `git rm --cached` of six session SQLite files. Fixtures (`tests/unit/memory/fixtures/legacy_memory.json`) kept. |
| SLON-029 | `MemoryRecord` | No provenance / scope / TTL / supersession | Added `MemoryProvenance`, `MemoryScope`, `ttl_seconds`, `superseded_by`. Persisted in `metadata` JSON (schema v4). `can_promote_to_personal` + `promote_to_personal`. Unverified/inferred/tool-obs cannot become PERSONAL. Retrieved text prefixed as UNTRUSTED DATA. |
| SLON-009 leftover | injector / context prefix | “trustworthy memory” wording | `DEFAULT_MEMORY_PREFIX` is untrusted DATA. |

## REMOVED LEGACY

- Live write path no longer calls `update_memory()` JSON saver.
- Runtime session DBs untracked (files may remain on disk; gitignore already covers them).
- `memory/memory_manager.py` remains for fail-closed extract gate and JSON load fallback when no `RuntimeStack.memory`.

## TESTS

| Command | Result |
| --- | --- |
| `python -m pytest tests/unit/memory/test_provenance.py tests/unit/memory/test_migrate.py tests/security/test_memory_trust_boundary.py tests/unit/memory/test_no_legacy_writes.py -q` | **15 passed** |
| `python -m pytest tests/unit/memory tests/security/test_memory_trust_boundary.py -q` | **70 passed** |

Full `pytest tests` not re-run in this wave (required after R3/R7/R10 and before R11).

## SECURITY

- ASSISTANT_UNVERIFIED cannot auto-promote to trusted personal fact.
- Retrieved memory is DATA, not instructions.
- JSON migration marks records `IMPORTED` / `PERSONAL`.
- Live extract is fail-closed in offline / local_only / fully_local (R1/R3).
- SQLite writes use WAL + busy_timeout + transactions.

## MIGRATIONS

- Legacy `memory/long_term.json` → `MemoryStore` via existing `migrate_json` when the SQLite store is empty.
- Provenance/scope stored in existing `metadata` column (no schema bump).

## KNOWN LIMITATIONS

- `memory/memory_manager.py` still exists; extract still uses Router `text_ops` (not SQLite-native extractor).
- `acta/selfimprovement` may still import `memory_manager` (caller cleanup R10).
- Dual-file presence is PARTIAL until R10 deletes unused JSON writer after caller proof.

## RUNTIME VERIFICATION STILL REQUIRED

- Live hardware: prompt contains untrusted memory block after extract.
- Crash during WAL write (process kill mid-commit) — unit covers propose/commit atomicity; OS crash not simulated here.

## COMMITS

Recorded after this file is committed with the wave.
