"""SDK imports are allowed only in providers/** and the onboard wizard."""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN = {
    "google.generativeai",
    "google.genai",
    "openai",
    "anthropic",
}

_ALLOW_PREFIXES = ("providers/",)
_ALLOW_FILES = {"config/onboard.py"}
_SKIP_PREFIXES = ("tests/", ".venv/", "ios/")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            if node.module == "google":
                for alias in node.names:
                    if alias.name in {"genai", "generativeai"}:
                        names.add(f"google.{alias.name}")
    return names


def test_sdk_imports_stay_on_provider_allowlist() -> None:
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(p) for p in _SKIP_PREFIXES):
            continue
        if rel in _ALLOW_FILES or any(rel.startswith(p) for p in _ALLOW_PREFIXES):
            continue
        imported = _imported_modules(path)
        {name for name in imported if name in _FORBIDDEN or name.split(".")[0] in _FORBIDDEN}
        # google.genai is forbidden; google alone is not (could be other pkgs)
        if "google.generativeai" in imported or "google.genai" in imported:
            violations.append(rel)
            continue
        if imported & {"openai", "anthropic"}:
            violations.append(rel)
    assert violations == []
