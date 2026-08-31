"""Memory-test fixtures. Database files stay under tmp_path."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from acta.memory import MemoryStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.sqlite"


@pytest.fixture
def store(db_path: Path) -> Generator[MemoryStore, None, None]:
    memory = MemoryStore(db_path)
    yield memory
    memory.close()
