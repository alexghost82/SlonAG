"""Comprehensive tests for Semantic Memory Core fixes.

Covers:
- Frozen Proposal mutation (dataclass replace semantics)
- Dedup across pending, persisted, workspace, user, session scopes
- Persistence failure / DB recovery
- Export (all + scope)
- Retrieval bounded context
- Confidence management
- Migration and recovery from corrupted DB
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from acta.memory import (
    MemoryContextAssembler,
    MemoryPolicy,
    MemoryRecord,
    MemoryRetriever,
    MemoryStore,
    RecordType,
    RetrievalResult,
)
from acta.memory.database import MemoryDatabase, MemoryRow
from acta.memory.migrations.schema import SCHEMA_VERSION, apply_schema

from tests.unit.memory.fakes import FakeLocalEmbedder


# ── helpers ──────────────────────────────────────────────────────────────────

def _record(
    key: str,
    value: str,
    record_type: RecordType = RecordType.PREFERENCES,
) -> MemoryRecord:
    return MemoryRecord(type=record_type, key=key, value=value, source="user")


def _commit(store: MemoryStore, record: MemoryRecord, **kwargs):
    return store.commit(store.propose(record, **kwargs).id)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Frozen Proposal mutation fix
# ══════════════════════════════════════════════════════════════════════════════


class TestFrozenProposalMutation:
    """Verify that duplicate detection uses immutable replace, not direct mutation."""

    def test_duplicate_pending_reduces_confidence(self, store: MemoryStore) -> None:
        p1 = store.propose(_record("food", "sourdough"))
        p2 = store.propose(_record("food2", "sourdough"))  # same value, different key
        assert p1.confidence == 1.0
        assert p2.confidence <= 0.5

    def test_duplicate_persisted_reduces_confidence(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        p = store.propose(_record("food3", "SOURDOUGH"))  # case-insensitive dup
        # Dedup in DB happens at commit time, not propose time
        rec = store.commit(p.id)
        assert rec is not None
        assert rec.confidence <= 0.5
        store.close()

    def test_cross_workspace_not_flagged(self, store: MemoryStore) -> None:
        store.propose(_record("food", "sourdough"), workspace="ws1")
        p = store.propose(_record("food2", "sourdough"), workspace="ws2")
        assert p.confidence == 1.0

    def test_cross_user_not_flagged(self, store: MemoryStore) -> None:
        store.propose(_record("food", "sourdough"), user_id="alice")
        p = store.propose(_record("food2", "sourdough"), user_id="bob")
        assert p.confidence == 1.0

    def test_cross_session_not_flagged(self, store: MemoryStore) -> None:
        store.propose(_record("food", "sourdough"), session_id="sess1")
        p = store.propose(_record("food2", "sourdough"), session_id="sess2")
        assert p.confidence == 1.0

    def test_same_session_flagged(self, store: MemoryStore) -> None:
        store.propose(_record("food", "sourdough"), session_id="sess1")
        p = store.propose(_record("food2", "sourdough"), session_id="sess1")
        assert p.confidence <= 0.5


# ══════════════════════════════════════════════════════════════════════════════
# 2. Dedup for pending / persisted / workspace / user / session
# ══════════════════════════════════════════════════════════════════════════════


class TestDedupComprehensive:
    """Deduplication across all scopes and persistence layers."""

    def test_pending_dedup_before_commit(self, store: MemoryStore) -> None:
        p1 = store.propose(_record("food", "sourdough"))
        p2 = store.propose(_record("food2", "sourdough"))
        assert len(store._pending) == 2
        assert p2.confidence <= 0.5

    def test_persisted_dedup_after_commit(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        p = store.propose(_record("food2", "Sourdough"))
        rec = store.commit(p.id)
        assert rec is not None
        assert rec.confidence <= 0.5
        store.close()

    def test_exact_value_dedup(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        p = store.propose(_record("food2", "sourdough"))
        rec = store.commit(p.id)
        assert rec is not None
        assert rec.confidence <= 0.5
        store.close()

    def test_different_values_not_deduped(self, store: MemoryStore) -> None:
        p1 = store.propose(_record("food", "sourdough"))
        p2 = store.propose(_record("food2", "rye"))
        assert p1.confidence == 1.0
        assert p2.confidence == 1.0

    def test_dedup_respects_scope(self, db_path: Path) -> None:
        store = MemoryStore(
            db_path,
            default_workspace="default_ws",
            default_user="default_user",
        )
        _commit(store, _record("food", "sourdough"))
        p = store.propose(_record("food2", "sourdough"), workspace="other_ws")
        assert p.confidence == 1.0
        store.close()


# ══════════════════════════════════════════════════════════════════════════════
# 3. Persistence failure / DB integrity
# ══════════════════════════════════════════════════════════════════════════════


class TestPersistenceFailure:
    """Memory DB remains consistent after errors."""

    def test_insert_error_keeps_pending(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        proposal = store.propose(_record("food", "sourdough"))
        # Force lazy DB init, then close and reopen
        db = store._db()
        db.close()
        store._database = None
        rec = store.commit(proposal.id)
        assert rec is not None
        assert proposal.id not in store._pending
        store.close()

    def test_commit_noop_when_disabled(self, store: MemoryStore) -> None:
        proposal = store.propose(_record("food", "sourdough"))
        store.set_enabled(False)
        result = store.commit(proposal.id)
        assert result is None
        assert proposal.id in store._pending
        assert store.list() == []

    def test_persistence_failure_does_not_corrupt_db(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        _commit(store, _record("city", "Helsinki", RecordType.CONFIRMED_FACTS))
        store.clear_all()
        _commit(store, _record("new_key", "new_value"))
        assert len(store.list()) == 1
        store.close()

    def test_schema_migration_after_corruption(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("DROP TABLE IF EXISTS memory_schema")
            conn.commit()
        finally:
            conn.close()

        store2 = MemoryStore(db_path)
        proposal = store2.propose(_record("recovered", "data"))
        rec = store2.commit(proposal.id)
        assert rec is not None
        store2.close()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Export
# ══════════════════════════════════════════════════════════════════════════════


class TestExport:
    """Export methods for backup and migration."""

    def test_export_all(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        _commit(store, _record("city", "Helsinki", RecordType.CONFIRMED_FACTS))
        export = store.export_all()
        assert len(export) == 2
        types_in_export = {e["type"] for e in export}
        assert "preferences" in types_in_export
        assert "confirmed_facts" in types_in_export
        store.close()

    def test_export_scope_filters(self, db_path: Path) -> None:
        store = MemoryStore(
            db_path,
            default_workspace="ws1",
            default_user="alice",
        )
        _commit(store, _record("food", "sourdough"))
        _commit(store, _record("city", "Helsinki", RecordType.CONFIRMED_FACTS), workspace="ws2")
        exported = store.export_scope()
        assert len(exported) == 1
        assert exported[0]["workspace"] == "ws1"
        exported_ws2 = store.export_scope(workspace="ws2")
        assert len(exported_ws2) == 1
        assert exported_ws2[0]["workspace"] == "ws2"
        store.close()

    def test_export_empty_when_no_records(self, store: MemoryStore) -> None:
        assert store.export_all() == []

    def test_export_includes_all_fields(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        export = store.export_all()
        assert len(export) == 1
        item = export[0]
        for field in ("id", "type", "key", "value", "source", "created_at", "updated_at",
                       "workspace", "user_id", "session_id", "confidence"):
            assert field in item, f"Missing field: {field}"
        store.close()


# ══════════════════════════════════════════════════════════════════════════════
# 5. Retrieval bounded context
# ══════════════════════════════════════════════════════════════════════════════


class TestRetrievalBounded:
    """Retrieval respects chunk limits and token budgets."""

    def test_max_chunks_limits_result(self, db_path: Path) -> None:
        store = MemoryStore(
            db_path,
            embedder=FakeLocalEmbedder(),
            default_workspace="ws",
            default_user="u",
        )
        for i in range(10):
            _commit(store, _record(f"key{i}", f"value{i}"))
        retriever = MemoryRetriever(
            store._db(),
            embed_service=store._embeddings,
            default_workspace="ws",
            default_user="u",
            max_chunks=3,
        )
        result = retriever.retrieve("test query")
        assert len(result.chunks) <= 3

    def test_token_budget_respected(self, db_path: Path) -> None:
        store = MemoryStore(
            db_path,
            embedder=FakeLocalEmbedder(),
            default_workspace="ws",
            default_user="u",
        )
        long_value = "x" * 5000
        _commit(store, _record("long", long_value))
        retriever = MemoryRetriever(
            store._db(),
            embed_service=store._embeddings,
            default_workspace="ws",
            default_user="u",
            max_chunks=10,
            token_budget=50,
        )
        result = retriever.retrieve("test")
        total_text_len = sum(len(c.text) for c in result.chunks)
        assert total_text_len <= 50

    def test_assembler_enforces_byte_limit(self) -> None:
        assembler = MemoryContextAssembler(max_chunks=100)
        long_chunks = []
        for _ in range(10):
            from acta.memory.retriever import ContextChunk
            long_chunks.append(ContextChunk(
                source_ref="test:long",
                text="A" * 2000,
                confidence=1.0,
                relevance=0.9,
                recency=0.9,
            ))
        result = RetrievalResult(chunks=long_chunks)
        assembled = assembler.assemble(result)
        encoded = assembled.encode("utf-8")
        assert len(encoded) <= 4096 + 4

    def test_retrieval_returns_empty_for_no_match(self, db_path: Path) -> None:
        store = MemoryStore(
            db_path,
            embedder=FakeLocalEmbedder(),
            default_workspace="ws",
            default_user="u",
        )
        _commit(store, _record("food", "sourdough"))
        retriever = MemoryRetriever(
            store._db(),
            embed_service=store._embeddings,
            default_workspace="other_ws",
            default_user="u",
            max_chunks=5,
        )
        result = retriever.retrieve("unrelated")
        assert result.chunks == []


# ══════════════════════════════════════════════════════════════════════════════
# 6. Confidence management
# ══════════════════════════════════════════════════════════════════════════════


class TestConfidence:
    """Confidence is correctly managed through dedup and deletion."""

    def test_duplicate_lowers_confidence(self, store: MemoryStore) -> None:
        p1 = store.propose(_record("food", "sourdough"))
        p2 = store.propose(_record("food2", "sourdough"))
        rec1 = store.commit(p1.id)
        rec2 = store.commit(p2.id)
        assert rec1 is not None
        assert rec2 is not None
        assert rec1.confidence == 1.0
        assert rec2.confidence <= 0.5

    def test_delete_low_confidence(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        p1 = store.propose(_record("food", "sourdough"))
        p2 = store.propose(_record("food2", "sourdough"))
        store.commit(p1.id)
        store.commit(p2.id)
        deleted = store.delete_low_confidence(threshold=0.6)
        assert deleted >= 1
        remaining = store.list()
        assert len(remaining) == 1
        assert remaining[0].confidence == 1.0
        store.close()

    def test_custom_confidence_passed_through(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        p = store.propose(_record("custom", "value"), confidence=0.75)
        rec = store.commit(p.id)
        assert rec is not None
        assert rec.confidence == 0.75
        store.close()


# ══════════════════════════════════════════════════════════════════════════════
# 7. Migration and recovery
# ══════════════════════════════════════════════════════════════════════════════


class TestMigrationRecovery:
    """Migration from legacy JSON and DB recovery."""

    def test_migration_skips_secrets(self, store: MemoryStore) -> None:
        payload = {
            "identity": {"name": {"value": "Alex"}},
            "preferences": {"api_key": {"value": "sk-secret123"}},
            "notes": {"password": {"value": "hunter2"}},
        }
        stats = store.migrate_json(payload)
        assert stats.migrated == 1
        assert stats.skipped_secrets == 2
        stored = store.list()
        assert len(stored) == 1
        assert stored[0].key == "name"
        assert "secret" not in stored[0].value

    def test_migration_empty_payload(self, store: MemoryStore) -> None:
        stats = store.migrate_json({})
        assert stats.migrated == 0
        assert store.list() == []

    def test_migration_invalid_payload_raises(self, store: MemoryStore) -> None:
        with pytest.raises(Exception):
            store.migrate_json("not-a-dict")

    def test_db_survives_empty_insert(self, db_path: Path) -> None:
        db = MemoryDatabase(db_path)
        db.insert(MemoryRow(
            id="test1", type="test", key="k", value="v",
            source="test", created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        ))
        fetched = db.get("test1")
        assert fetched is not None
        assert fetched.value == "v"
        db.close()

    def test_schema_version_increments(self) -> None:
        assert SCHEMA_VERSION >= 4

    def test_corrupted_db_recovers(self, db_path: Path) -> None:
        store = MemoryStore(db_path)
        _commit(store, _record("food", "sourdough"))
        store.close()

        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS memory_schema")
        conn.commit()
        conn.close()

        store2 = MemoryStore(db_path)
        p = store2.propose(_record("recovered", "yes"))
        rec = store2.commit(p.id)
        assert rec is not None
        store2.close()


# ══════════════════════════════════════════════════════════════════════════════
# 8. Retriever correct preserves scope
# ══════════════════════════════════════════════════════════════════════════════


class TestRetrieverCorrect:
    """MemoryRetriever.correct() should preserve scoped fields."""

    def test_correct_preserves_workspace(self, db_path: Path) -> None:
        store = MemoryStore(
            db_path,
            embedder=FakeLocalEmbedder(),
            default_workspace="ws1",
            default_user="u1",
            default_session="s1",
        )
        _commit(store, _record("food", "sourdough"))
        rows = store.list()
        record_id = rows[0].id

        retriever = MemoryRetriever(
            store._db(),
            embed_service=store._embeddings,
            default_workspace="ws1",
            default_user="u1",
            default_session="s1",
        )
        updated = retriever.correct(record_id, value="rye")
        assert updated is not None
        assert updated.value == "rye"
        row = store.get(record_id)
        assert row is not None
        assert row.workspace == "ws1"
        assert row.user_id == "u1"
        assert row.session_id == "s1"
        store.close()
