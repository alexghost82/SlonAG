"""Scan production files for hardcoded English user-facing strings.

Run: pytest tests/unit/test_i18n_scan.py -v
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

_I18N_EN_PATH = Path(__file__).resolve().parent.parent.parent / 'i18n' / 'en.json'


def _get_i18n_keys() -> set[str]:
    """Return all keys from i18n/en.json as a flat set."""
    try:
        data = json.loads(_I18N_EN_PATH.read_text('utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    keys: set[str] = set()

    def _flatten(obj: dict, parent: str = '') -> None:
        for k, v in obj.items():
            new_key = f'{parent}.{k}' if parent else k
            if isinstance(v, dict):
                _flatten(v, new_key)
            else:
                keys.add(new_key)

    _flatten(data)
    return keys


def _file_has_t_import(filepath: Path) -> bool:
    """Check if the file imports t from i18n."""
    try:
        source = filepath.read_text('utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == 'i18n':
                    for alias in node.names:
                        if alias.name in ('t', '_'):
                            return True
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'i18n':
                        return True
    except SyntaxError:
        pass
    return False


def _has_user_facing_output(filepath: Path) -> bool:
    """Check if file has write_log or print calls."""
    try:
        source = filepath.read_text('utf-8')
        return bool(re.search(r'\.write_log\s*\(|\bprint\s*\(', source))
    except Exception:
        return False


class TestI18nScan:
    """Lightweight scan for untranslated user-facing strings."""

    def test_i18n_json_valid(self, project_root: Path) -> None:
        """i18n/en.json and i18n/ru.json must be valid JSON."""
        try:
            json.loads(_I18N_EN_PATH.read_text('utf-8'))
        except FileNotFoundError:
            pytest.fail('i18n/en.json not found')
        ru_path = _I18N_EN_PATH.parent / 'ru.json'
        try:
            json.loads(ru_path.read_text('utf-8'))
        except FileNotFoundError:
            pytest.fail('i18n/ru.json not found')

    def test_i18n_keys_match(self, project_root: Path) -> None:
        """i18n/en.json and i18n/ru.json must have same structure."""
        en = json.loads(_I18N_EN_PATH.read_text('utf-8'))
        ru = json.loads((_I18N_EN_PATH.parent / 'ru.json').read_text('utf-8'))

        def _top_keys(d: dict) -> set[str]:
            keys: set[str] = set()
            for k, v in d.items():
                if isinstance(v, dict):
                    keys.add(k)
                    keys.update(_top_keys(v))
                else:
                    keys.add(f'{k}')
            return keys

        en_keys = set(en.keys())
        ru_keys = set(ru.keys())
        assert en_keys == ru_keys, (
            f'Top-level keys differ: only in en={en_keys - ru_keys}, '
            f'only in ru={ru_keys - en_keys}'
        )

    def test_no_fabricated_keys(self, project_root: Path) -> None:
        """Every t("...") key used in Python files must exist in i18n."""
        i18n_keys = _get_i18n_keys()
        if not i18n_keys:
            pytest.skip('i18n keys not loaded')

        bad_keys: list[str] = []
        t_pattern = re.compile(r"""(?<!\w)t\(\s*(?:"([^"]+)"|'([^']+))\s*(?:,|\))""")

        for src_file in sorted(project_root.glob('**/*.py')):
            # Skip non-source directories
            parts = src_file.parts
            if any(p in ('.venv', '.git', '__pycache__', 'node_modules',
                         'build', 'dist', 'tests', 'i18n', '.pytest_cache')
                   for p in parts):
                continue
            try:
                source = src_file.read_text('utf-8')
            except Exception:
                continue
            # Only check files that actually import t from i18n
            if not _file_has_t_import(src_file):
                continue
            for m in t_pattern.finditer(source):
                key = m.group(1)
                if key not in i18n_keys:
                    bad_keys.append(key)

        assert bad_keys == [], (
            f'Keys used in t() not found in i18n: '
            f'{", ".join(bad_keys[:10])}'
        )

    def test_actions_have_t_import(self, project_root: Path) -> None:
        """All production action files should import t from i18n."""
        actions_dir = project_root / 'actions'
        py_files = list(actions_dir.glob('*.py'))
        missing: list[str] = []
        for f in py_files:
            if f.name in ('__pycache__', '__init__.py'):
                continue
            if f.is_file() and _has_user_facing_output(f) and not _file_has_t_import(f):
                missing.append(f.name)
        assert missing == [], (
            f'Action files with user-facing output but no i18n import: '
            f'{", ".join(missing)}'
        )

    def test_standalone_have_t_import(self, project_root: Path) -> None:
        """Core standalone files should import t from i18n."""
        standalone = [
            'setup.py', 'or_client.py', 'runtime/smoke.py',
            'agent/error_handler.py', 'agent/task_queue.py',
            'memory/memory_manager.py', 'server/__main__.py',
            'speech/tts/__main__.py',
        ]
        missing: list[str] = []
        for name in standalone:
            p = project_root / name
            if not p.exists():
                continue
            if not _file_has_t_import(p) and _has_user_facing_output(p):
                missing.append(name)
        assert missing == [], (
            f'Standalone files with user-facing output but no i18n import: '
            f'{", ".join(missing)}'
        )

    def test_all_keys_exist_in_ru(self, project_root: Path) -> None:
        """All keys from en must exist in ru."""
        en = json.loads(_I18N_EN_PATH.read_text('utf-8'))
        ru = json.loads((_I18N_EN_PATH.parent / 'ru.json').read_text('utf-8'))

        def _flatten(d: dict, prefix: str = '') -> dict:
            result: dict = {}
            for k, v in d.items():
                key = f'{prefix}.{k}' if prefix else k
                if isinstance(v, dict):
                    result.update(_flatten(v, key))
                else:
                    result[key] = v
            return result

        en_flat = _flatten(en)
        missing: list[str] = []
        for k in en_flat:
            parts = k.split('.')
            node = ru
            found = True
            for p in parts:
                if isinstance(node, dict) and p in node:
                    node = node[p]
                else:
                    found = False
                    break
            if not found:
                missing.append(k)

        assert missing == [], (
            f'Keys missing from ru.json: '
            f'{", ".join(missing[:10])}'
        )
