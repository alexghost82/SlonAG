"""Desktop UI must talk to Core only through the control plane."""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN_PREFIXES = (
    "agent.runtime",
    "acta.tools.executor",
    "acta.tools.legacy",
    "providers.router",
    "providers.gemini.live",
    "google.genai",
    "google.generativeai",
)
_UI_PATHS = ("ui.py", "ui/")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_ui_does_not_import_core_runtimes() -> None:
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    candidates = [root / "ui.py"]
    ui_dir = root / "ui"
    if ui_dir.is_dir():
        candidates.extend(ui_dir.rglob("*.py"))
    for path in candidates:
        if not path.exists():
            continue
        imported = _imports(path)
        bad = [
            name
            for name in imported
            if name in _FORBIDDEN_PREFIXES
            or any(name.startswith(prefix + ".") for prefix in _FORBIDDEN_PREFIXES)
        ]
        if bad:
            violations.append(f"{path.relative_to(root)}: {sorted(bad)}")
    assert violations == []


def test_agent_loop_does_not_import_gemini_live() -> None:
    root = Path(__file__).resolve().parents[2]
    runtime = root / "agent" / "runtime.py"
    imported = _imports(runtime)
    assert "providers.gemini.live" not in imported
    assert "google.genai" not in imported
    assert "runtime.live_session" not in imported
