# Tooling Guide

This project uses [pyproject.toml](/pyproject.toml) to configure all developer tools.

## Quick start

```bash
# 1. Install dev dependencies
pip install -e ".[dev]"

# 2. Install pre-commit hooks
pre-commit install

# 3. Run linters
ruff check .
ruff format --check .
mypy

# 4. Run tests
pytest

# 5. Full check (lint + format + mypy + tests)
pre-commit run --all-files && pytest
```

## Tools

| Tool | Config section | Scope |
|------|---------------|-------|
| **pytest** | `[tool.pytest]` | `tests/` |
| **ruff** | `[tool.ruff]` | tests + core modules (legacy excluded) |
| **mypy** | `[tool.mypy]` | tests + core modules (legacy deferred) |
| **coverage** | `[tool.coverage]` | application code (tests/actions excluded) |

### Ruff

- Auto-fix enabled via pre-commit (`ruff --fix`).
- Rules: `E` (pycodestyle errors), `F` (pyflakes), `W` (pyflakes), `UP` (pyupgrade), `I` (isort).
- Legacy modules (`actions/`, `agent/`, `or_client.py`, `memory/`) are excluded.

### MyPy

- Python 3.11 target.
- Legacy modules have `ignore_errors = true`.
- External library stubs (`pyautogui`, `cv2`, `google`, etc.) are ignored for missing imports.

### Pre-commit hooks

1. **trailing-whitespace** — strips trailing whitespace
2. **end-of-file-fixer** — ensures files end with newline
3. **mixed-line-ending** — normalises to LF
4. **check-yaml** — validates YAML files
5. **check-toml** — validates TOML files
6. **check-json** — validates JSON files
7. **check-merge-conflict** — flags unresolved merge markers
8. **ruff** — lint with auto-fix
9. **ruff-format** — format code
10. **gitleaks** — detect leaked secrets/keys

## Running the app

```bash
python main.py           # direct execution
python -m main           # module execution
slon                     # via pyproject console script (requires GUI)
```

## Adding a new Python module

1. Create the `.py` file.
2. If it belongs to a "core" module (not legacy), add it to the ruff `include` list and mypy `files` list in [pyproject.toml](/pyproject.toml).
3. Write tests in `tests/`.
4. Run `pre-commit run <file>` before committing.
