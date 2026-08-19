"""Headless-friendly checks for UI runtime glue helpers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ui_module_imports_optional_stacks() -> None:
    """Import ui symbols used by glue without constructing QApplication."""
    import ast

    tree = ast.parse((ROOT / "ui.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    names.add(item.name)
    assert "_init_runtime_bridge" in names
    assert "_init_local_tts" in names
    assert "_toggle_desktop_api" in names


def test_file_drop_zone_no_longer_owns_tts_init() -> None:
    import ast

    tree = ast.parse((ROOT / "ui.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FileDropZone":
            methods = {
                item.name
                for item in node.body
                if isinstance(item, ast.FunctionDef)
            }
            assert "_init_local_tts" not in methods
            init = next(
                item
                for item in node.body
                if isinstance(item, ast.FunctionDef) and item.name == "__init__"
            )
            src = ast.get_source_segment(
                (ROOT / "ui.py").read_text(encoding="utf-8"),
                init,
            )
            assert src is not None
            assert "_init_local_tts" not in src
            return
    raise AssertionError("FileDropZone not found")
