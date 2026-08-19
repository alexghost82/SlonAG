from __future__ import annotations

from mark.memory import MemoryRecord, MemoryStore, RecordType

from tests.unit.memory.fakes import FakeCloudEmbedder, FakeLocalEmbedder


def _draft() -> MemoryRecord:
    return MemoryRecord(
        type=RecordType.SUMMARIES,
        key="meeting",
        value="weekly sync on Mondays",
        source="user",
    )


def test_fully_local_does_not_call_cloud_embedder(db_path) -> None:
    cloud = FakeCloudEmbedder()
    store = MemoryStore(
        db_path,
        embedder=cloud,
        privacy_profile="fully_local",
        network_mode="hybrid",
    )
    proposal = store.propose(_draft())
    record = store.commit(proposal.id)
    assert record is not None
    assert cloud.calls == []
    store.close()


def test_offline_does_not_call_cloud_embedder(db_path) -> None:
    cloud = FakeCloudEmbedder()
    store = MemoryStore(
        db_path,
        embedder=cloud,
        privacy_profile="cloud",
        network_mode="offline",
    )
    proposal = store.propose(_draft())
    record = store.commit(proposal.id)
    assert record is not None
    assert cloud.calls == []
    store.close()


def test_local_embedder_is_called_when_fully_local(db_path) -> None:
    local = FakeLocalEmbedder()
    store = MemoryStore(
        db_path,
        embedder=local,
        privacy_profile="fully_local",
        network_mode="offline",
    )
    proposal = store.propose(_draft())
    record = store.commit(proposal.id)
    assert record is not None
    assert local.calls == ["weekly sync on Mondays"]
    store.close()
