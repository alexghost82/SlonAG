"""Shared pytest fixtures for the unit-test harness.

Fixtures here must not read config/api_keys.json or touch the network.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root (the directory that contains pyproject.toml)."""
    return Path(__file__).resolve().parents[1]
