"""Unit tests for memory get/delete via injected store."""

from __future__ import annotations

from pathlib import Path

from server.routes._common import DevicePrincipal
from server.routes.memory import MemoryHandler, MemoryStore
from server.schemas import MemoryEntry


def test_memory_get_unauthenticated_returns_401() -> None:
    handler = MemoryHandler()
    response = handler.get_memory(principal=None)
    assert response.status_code == 401


def test_memory_get_and_delete_via_injected_store(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    store = MemoryStore(
        entries=(
            MemoryEntry(id="mem_1", kind="note", summary="alpha"),
            MemoryEntry(id="mem_2", kind="note", summary="beta"),
        )
    )
    handler = MemoryHandler(store=store)
    principal = DevicePrincipal(device_id="dev_ok")

    listed = handler.get_memory(principal=principal)
    assert listed.status_code == 200
    assert len(listed.body["entries"]) == 2  # type: ignore[arg-type]

    # Snapshot legacy memory dir before delete — must remain untouched.
    legacy_dir = repo_root / "memory"
    before_names = (
        {p.name for p in legacy_dir.glob("*.json")} if legacy_dir.is_dir() else set()
    )
    before_mtimes = {
        name: (legacy_dir / name).stat().st_mtime_ns for name in before_names
    }

    deleted = handler.delete(
        principal=principal,
        memory_id="mem_1",
        body={"idempotency_key": "mem-del-1"},
    )
    assert deleted.status_code == 200
    assert deleted.body["deleted"] is True
    assert len(store.list_entries()) == 1
    assert store.list_entries()[0].id == "mem_2"

    after_names = (
        {p.name for p in legacy_dir.glob("*.json")} if legacy_dir.is_dir() else set()
    )
    assert after_names == before_names
    for name in after_names:
        assert (legacy_dir / name).stat().st_mtime_ns == before_mtimes[name]

    # Handler must not create any JSON under tmp either as a side channel.
    assert list(tmp_path.glob("**/*.json")) == []


def test_memory_delete_idempotent() -> None:
    store = MemoryStore(entries=(MemoryEntry(id="mem_x", kind="note"),))
    handler = MemoryHandler(store=store)
    principal = DevicePrincipal(device_id="dev_ok")
    body = {"idempotency_key": "del-x"}
    first = handler.delete(principal=principal, memory_id="mem_x", body=body)
    second = handler.delete(principal=principal, memory_id="mem_x", body=body)
    assert first.body == second.body
    assert handler.idempotency.side_effect_count("memory_delete:del-x") == 1
