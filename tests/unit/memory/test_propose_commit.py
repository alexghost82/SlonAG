from __future__ import annotations

from pathlib import Path

import pytest
import sqlite3

from acta.memory import (
    CODE_UNKNOWN_PROPOSAL,
    MemoryRecord,
    MemoryStore,
    MemoryStoreError,
    RecordType,
)


def _draft(
    *,
    key: str = "food",
    value: str = "sourdough",
    record_type: RecordType = RecordType.PREFERENCES,
    source: str = "user",
) -> MemoryRecord:
    return MemoryRecord(type=record_type, key=key, value=value, source=source)


def test_propose_does_not_persist(store: MemoryStore, db_path: Path) -> None:
    proposal = store.propose(_draft())
    assert proposal.id
    assert proposal.key == "food"
    assert not db_path.exists()
    assert store.list() == []
    assert store.get(proposal.id) is None
    if db_path.exists():
        connection = sqlite3.connect(db_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM memory_records").fetchone()
            assert count is not None
            assert count[0] == 0
        except sqlite3.OperationalError:
            pass
        finally:
            connection.close()


def test_commit_persists_proposal(store: MemoryStore) -> None:
    proposal = store.propose(_draft())
    record = store.commit(proposal.id)
    assert record is not None
    assert record.id == proposal.id
    assert record.key == "food"
    assert record.value == "sourdough"
    assert record.source == "user"
    assert record.type is RecordType.PREFERENCES
    assert record.created_at
    assert record.updated_at
    stored = store.get(record.id)
    assert stored == record
    listed = store.list()
    assert listed == [record]


def test_commit_unknown_proposal_raises(store: MemoryStore) -> None:
    with pytest.raises(MemoryStoreError) as exc_info:
        store.commit("missing-proposal")
    assert exc_info.value.code == CODE_UNKNOWN_PROPOSAL


def test_commit_is_noop_when_disabled(store: MemoryStore, db_path: Path) -> None:
    proposal = store.propose(_draft())
    store.set_enabled(False)
    assert store.enabled is False
    assert store.commit(proposal.id) is None
    store.set_enabled(True)
    assert store.list() == []
    if db_path.exists():
        connection = sqlite3.connect(db_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM memory_records").fetchone()
            assert count is not None
            assert count[0] == 0
        except sqlite3.OperationalError:
            pass
        finally:
            connection.close()
