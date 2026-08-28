"""Shared fixtures for SlonAG tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Root of the SlonAG project (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root() -> Path:
    """Root of the SlonAG project (alias for project_root)."""
    return project_root
