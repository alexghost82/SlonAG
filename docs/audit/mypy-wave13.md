# Mypy status (Wave 13 → Wave 14)

## Command

```bash
mypy --config-file=pyproject.toml --no-incremental
```

Used: mypy 1.14.1 on Python 3.12 (`/tmp/mark-mypy-venv`).

## Counts

| Stage | Errors |
|---|---|
| Wave 13 after cleanup | 25 |
| Wave 14 | **0** (212 source files) |

Legacy `actions.*` / `agent.*` / `or_client` / `memory.*` remain under `ignore_errors` overrides (pre-existing debt outside new stack).
