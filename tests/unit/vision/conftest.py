"""Vision-test fixtures. Isolated from config secrets and the network."""

from __future__ import annotations

import pytest

from providers.registry import clear


@pytest.fixture
def clean_registry():
    """Empty the process-wide registry around each test."""
    clear()
    yield
    clear()
