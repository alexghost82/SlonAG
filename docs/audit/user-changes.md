# User-change boundary inventory

Scan date: **2026-08-15**

Read-only sources:

- `openclaw` — `/Users/slon/.openclaw/workspace/Slon` (`main` @ `eac6378`)
- `cursor-workspace` — `/Users/slon/SillyTavern/Slon` (`main` @ `eac6378`)

Command used in both trees: `git status --short`.

This integration clone must not receive secrets, key material, or user memory. Secret-bearing files are recorded as **present, redacted** only. No values from `config/api_keys.json` or `memory/*.json` are copied here.

## Inventory

| path | location | type | classification | target wave or task | notes |
| --- | --- | --- | --- | --- | --- |
| `actions/game_updater.py` | openclaw | modified tracked | later-port | W01-T04 | Local winreg import guard (`try/except ImportError` plus `winreg is None` early-returns in Steam/Epic path lookup). Do not patch from this task. |
| `config/api_keys.json` | openclaw | untracked | never-port | — | Live secrets. Present, redacted. Never copy values or file contents. |
| `memory/long_term.json` | openclaw | untracked | never-port | — | User memory. Present, redacted. Never copy payloads or file contents. |
| `requirements-macos.txt` | openclaw | untracked | later-port | W01-T02 | Local macOS Python dependency list (package names only; no secrets). |
| `run_mark.sh` | openclaw | untracked | later-port | later launcher task | Local zsh launcher: `cd` to repo root and `exec .venv/bin/python main.py`. Candidate for a later launcher task. |
| `.venv/` | openclaw | untracked | never-port | — | Local virtualenv and installed packages. Generated artifact. |
| `__pycache__/` | openclaw | untracked | never-port | — | Root bytecode cache. Generated artifact. |
| `actions/__pycache__/` | openclaw | untracked | never-port | — | Package bytecode cache. Generated artifact. Newly listed beyond the known root `__pycache__/`. |
| `agent/__pycache__/` | openclaw | untracked | never-port | — | Package bytecode cache. Generated artifact. Newly listed beyond the known root `__pycache__/`. |
| `config/__pycache__/` | openclaw | untracked | never-port | — | Package bytecode cache. Generated artifact. Newly listed beyond the known root `__pycache__/`. |
| `memory/__pycache__/` | openclaw | untracked | never-port | — | Package bytecode cache. Generated artifact. Newly listed beyond the known root `__pycache__/`. |
| `macos-app/` | openclaw | untracked | never-port | — | Local macOS bundle directory. Contains `Slon.app`. Do not port blindly. |
| `.DS_Store` | cursor-workspace | untracked | never-port | — | Finder metadata. |
| `CODE_AGENT_IMPLEMENTATION_PLAN.md` | cursor-workspace | untracked | later-port | integrator review (no dedicated task) | User-authored Russian implementation plan. Header inspected; no secrets. Port only after integrator review; not an executable contract. |
| `Slon/` | cursor-workspace | untracked | never-port | — | Nested duplicate clone. Do not copy into the integration tree. |

## Coverage

Every path from both `git status --short` listings is accounted for above. `.git` internals were excluded.

OpenClaw listing (12 paths):

```text
 M actions/game_updater.py
?? .venv/
?? __pycache__/
?? actions/__pycache__/
?? agent/__pycache__/
?? config/__pycache__/
?? config/api_keys.json
?? macos-app/
?? memory/__pycache__/
?? memory/long_term.json
?? requirements-macos.txt
?? run_mark.sh
```

Cursor-workspace listing (3 paths):

```text
?? .DS_Store
?? CODE_AGENT_IMPLEMENTATION_PLAN.md
?? Slon/
```

## Newly discovered relative to the task brief

- Per-package `__pycache__/` directories in OpenClaw: `actions/`, `agent/`, `config/`, `memory/` (in addition to the known root `__pycache__/`).
- `macos-app/` contains a local `.app` bundle named `Slon.app`.

## Classification summary

| classification | count | items |
| --- | --- | --- |
| later-port | 4 | `actions/game_updater.py` → W01-T04; `requirements-macos.txt` → W01-T02; `run_mark.sh` → later launcher task; `CODE_AGENT_IMPLEMENTATION_PLAN.md` → integrator review |
| never-port | 11 | secrets, memory, `.venv/`, all `__pycache__/`, `macos-app/` (`.app` bundle), `.DS_Store`, nested `Slon/` |
| already-isolated | 0 | none in these two working copies |

## Integration notes

- Do not copy `config/api_keys.json` or `memory/long_term.json` into this clone. Values are present in OpenClaw and redacted here.
- Do not apply the OpenClaw `game_updater.py` winreg-guard from this task; W01-T04 owns that port.
- Do not import `.venv/`, `__pycache__/`, `.app` bundles, `.DS_Store`, or the nested Cursor clone.
- `run_mark.sh` is a thin local launcher and should wait for a dedicated launcher task rather than being copied ad hoc.
- `CODE_AGENT_IMPLEMENTATION_PLAN.md` is planning source only; extract requirements through the integrator, do not merge the file wholesale.
