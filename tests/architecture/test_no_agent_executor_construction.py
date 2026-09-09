"""Production code must not construct AgentExecutor. Tests may import it explicitly."""

from __future__ import annotations

import ast
from pathlib import Path

PRODUCTION_ROOTS = (
    "agent",
    "acta",
    "main.py",
    "server",
    "gateway",
    "sessions",
    "runtime",
)


def _is_agent_executor_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "AgentExecutor"
    if isinstance(func, ast.Attribute):
        return func.attr == "AgentExecutor"
    return False


def _scan(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if _is_agent_executor_call(node):
            hits.append(f"{path}:{node.lineno}")
    return hits


def test_production_does_not_construct_agent_executor() -> None:
    root = Path(__file__).resolve().parents[2]
    hits: list[str] = []
    for name in PRODUCTION_ROOTS:
        target = root / name
        if target.is_file() and target.suffix == ".py":
            hits.extend(_scan(target))
            continue
        if not target.is_dir():
            continue
        for path in target.rglob("*.py"):
            hits.extend(_scan(path))
    assert hits == []
