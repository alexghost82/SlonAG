"""Harness smoke tests.

These must collect and pass without config/api_keys.json and without network.
Sibling test trees (config/, requirements/, actions/) may be absent.
Do not import unfinished sibling application modules.
"""

import sys
from pathlib import Path


def test_harness_runs() -> None:
    assert True


def test_repo_root_is_importable(repo_root: Path) -> None:
    assert repo_root.is_dir()
    assert (repo_root / "pyproject.toml").is_file()
    assert (repo_root / "requirements-dev.txt").is_file()
    resolved_root = repo_root.resolve()
    assert any(Path(entry).resolve() == resolved_root for entry in sys.path if entry)


def test_api_keys_json_is_not_required_to_collect_tests(repo_root: Path) -> None:
    """Collection already succeeded without opening config/api_keys.json."""
    api_keys = repo_root / "config" / "api_keys.json"
    # Reaching this test is the proof: pytest collected this module
    # whether or not a local secrets file exists.
    assert not api_keys.exists() or api_keys.is_file()
