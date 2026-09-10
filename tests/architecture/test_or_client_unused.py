"""Production code must not import the retired root or_client module."""

from __future__ import annotations

import ast
from pathlib import Path

_SKIP_PREFIXES = ("tests/", "docs/", ".venv/", "ios/")


def test_or_client_is_not_imported_outside_tests() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "or_client.py").exists()
    violations: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "or_client" or alias.name.startswith("or_client."):
                        violations.append(rel)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "or_client" or node.module.startswith("or_client."):
                    violations.append(rel)
    assert violations == []
