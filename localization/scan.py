"""Find likely hardcoded user-facing string literals in Python source."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

_LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
_WHITESPACE = re.compile(r"\s")


@dataclass(frozen=True)
class StringHit:
    """A string literal that looks like user-facing UI copy."""

    value: str
    lineno: int
    col_offset: int


def find_hardcoded_strings(source: str) -> list[StringHit]:
    """Return likely user-facing literals that are not passed to ``tr()``.

    Intended for later UI migration. Docstrings and ``tr("key")`` arguments
    are ignored. Phrases such as ``"Type a command"`` are reported.
    """
    if not isinstance(source, str):
        raise TypeError("find_hardcoded_strings() expected a source string")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"cannot parse Python source: {exc}") from exc

    skip_ids = _tr_argument_ids(tree)
    skip_ids.update(_docstring_ids(tree))

    hits: list[StringHit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip_ids:
            continue
        if not _looks_user_facing(node.value):
            continue
        hits.append(
            StringHit(
                value=node.value,
                lineno=getattr(node, "lineno", 0),
                col_offset=getattr(node, "col_offset", 0),
            )
        )
    hits.sort(key=lambda hit: (hit.lineno, hit.col_offset, hit.value))
    return hits


def _is_tr_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "tr"
    if isinstance(func, ast.Attribute):
        return func.attr == "tr"
    return False


def _tr_argument_ids(tree: ast.AST) -> set[int]:
    skip: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_tr_call(node):
            continue
        args = list(node.args) + [keyword.value for keyword in node.keywords]
        for arg in args:
            for child in ast.walk(arg):
                skip.add(id(child))
    return skip


def _docstring_ids(tree: ast.AST) -> set[int]:
    skip: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            skip.add(id(value))
    return skip


def _looks_user_facing(value: str) -> bool:
    if not value or not value.strip():
        return False
    if not _LETTER.search(value):
        return False
    return _WHITESPACE.search(value) is not None
