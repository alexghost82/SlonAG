from __future__ import annotations

from pathlib import Path

from acta.memory import MemoryRecord, MemoryStore, RecordType
from tests.unit.memory.test_migrate import FIXTURE


def test_store_does_not_write_memory_json(store: MemoryStore, repo_root: Path) -> None:
    memory_dir = repo_root / "memory"
    existing = memory_dir.glob("*.json") if memory_dir.exists() else ()
    before = {path.name for path in existing}
    proposal = store.propose(
        MemoryRecord(
            type=RecordType.PREFERENCES,
            key="food",
            value="sourdough",
            source="user",
        )
    )
    store.commit(proposal.id)
    store.migrate_json(FIXTURE)
    store.update(proposal.id, value="rye")
    store.clear_all()
    remaining = memory_dir.glob("*.json") if memory_dir.exists() else ()
    after = {path.name for path in remaining}
    assert after == before
    assert not (memory_dir / "long_term.json").exists() or "long_term.json" in before


def test_update_memory_does_not_write_json(tmp_path: Path, monkeypatch, repo_root: Path) -> None:
    import memory.memory_manager as mm

    monkeypatch.setattr(mm, "_CANONICAL_DB", tmp_path / "mark_memory.sqlite3")
    memory_dir = repo_root / "memory"
    before = {p.name for p in memory_dir.glob("*.json")} if memory_dir.exists() else set()
    mm.update_memory({"notes": {"k": {"value": "canonical-only"}}})
    after = {p.name for p in memory_dir.glob("*.json")} if memory_dir.exists() else set()
    assert after == before
    assert not (tmp_path / "long_term.json").exists()


def test_package_does_not_import_legacy_or_client(repo_root: Path) -> None:
    root = repo_root / "mark" / "memory"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "or_client" not in text
        assert "memory_manager" not in text
        assert "from memory " not in text
        assert "import memory." not in text
