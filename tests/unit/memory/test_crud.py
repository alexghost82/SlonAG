from __future__ import annotations

from mark.memory import MemoryRecord, MemoryStore, RecordType


def _record(
    key: str,
    value: str,
    record_type: RecordType = RecordType.PREFERENCES,
) -> MemoryRecord:
    return MemoryRecord(type=record_type, key=key, value=value, source="user")


def _commit(store: MemoryStore, record: MemoryRecord):
    return store.commit(store.propose(record).id)


def test_list_get_update_delete(store: MemoryStore) -> None:
    first = _commit(store, _record("food", "sourdough"))
    second = _commit(
        store,
        _record("mark", "desktop client", RecordType.PROJECTS),
    )
    assert first is not None
    assert second is not None
    assert {item.id for item in store.list()} == {first.id, second.id}
    projects = store.list(RecordType.PROJECTS)
    assert [item.id for item in projects] == [second.id]
    assert store.get(first.id) == first

    updated = store.update(first.id, value="rye")
    assert updated is not None
    assert updated.value == "rye"
    assert updated.id == first.id
    assert updated.created_at == first.created_at
    assert updated.updated_at >= first.updated_at
    got = store.get(first.id)
    assert got is not None
    assert got.value == "rye"

    assert store.delete(second.id) is True
    assert store.get(second.id) is None
    assert [item.id for item in store.list()] == [first.id]


def test_clear_all_removes_records(store: MemoryStore) -> None:
    _commit(store, _record("food", "sourdough"))
    _commit(store, _record("city", "Helsinki", RecordType.CONFIRMED_FACTS))
    assert len(store.list()) == 2
    removed = store.clear_all()
    assert removed == 2
    assert store.list() == []


def test_writes_are_noop_when_disabled(store: MemoryStore) -> None:
    kept = _commit(store, _record("food", "sourdough"))
    assert kept is not None
    store.set_enabled(False)
    assert store.update(kept.id, value="rye") is None
    got = store.get(kept.id)
    assert got is not None
    assert got.value == "sourdough"
    assert store.delete(kept.id) is False
    assert store.get(kept.id) is not None
    assert store.clear_all() == 0
    assert store.list() == [store.get(kept.id)]
    later = store.propose(_record("city", "Helsinki", RecordType.CONFIRMED_FACTS))
    assert store.commit(later.id) is None
    assert len(store.list()) == 1
