"""Fixtures for local document ingest tests. No network, no API keys."""

from __future__ import annotations

from pathlib import Path

import pytest

from acta.documents import DocumentIngestor


@pytest.fixture
def ingest_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


@pytest.fixture
def ingest_temp(tmp_path: Path) -> Path:
    temp = tmp_path / "tmp"
    temp.mkdir()
    return temp


@pytest.fixture
def ingestor(ingest_root: Path, ingest_temp: Path) -> DocumentIngestor:
    return DocumentIngestor(root=ingest_root, temp_dir=ingest_temp)
