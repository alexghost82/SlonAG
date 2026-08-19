# Tests

Install developer tools, then run the unit-test harness:

```text
python -m pip install -r requirements-dev.txt
python -m pytest tests/unit -q
python -m ruff check .
```

Optional typecheck of the harness (scoped to `tests/` in `pyproject.toml`):

```text
python -m mypy
```

`python -m pytest tests/unit` must pass even when sibling trees such as
`tests/unit/config`, `tests/unit/requirements`, or `tests/unit/actions` are
absent. Collection does not require `config/api_keys.json` or network access.

Ruff is scoped to `tests/` so legacy application files (`main.py`, `ui.py`,
and the rest of the runtime tree) are not a required rewrite in this wave.
Runtime dependencies are not installed by this harness; they belong to
`requirements-*.txt`.
