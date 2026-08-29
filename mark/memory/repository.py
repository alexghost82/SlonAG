"""Propose-then-commit memory store. The model path never opens SQLite."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from mark.memory.database import MemoryDatabase, MemoryRow
from mark.memory.embeddings import Embedder, EmbeddingService
from mark.memory.errors import (
    CODE_INVALID_RECORD,
    CODE_UNKNOWN_PROPOSAL,
    CODE_UNKNOWN_TYPE,
    MemoryStoreError,
)
from mark.memory.policy import MemoryPolicy


class RecordType(StrEnum):
    PREFERENCES = "preferences"
    PROJECTS = "projects"
    CONFIRMED_FACTS = "confirmed_facts"
    SUMMARIES = "summaries"
    ACTION_HISTORY = "action_history"


@dataclass(frozen=True)
class MemoryRecord:
    """One memory item. Drafts may omit id and timestamps."""

    type: RecordType
    key: str
    value: str
    source: str
    id: str = ""
    created_at: str = ""
    updated_at: str = ""
    # ── scoping fields (v2+) ──────────────────────────────────────────
    dedup_hash: str = ""
    workspace: str = ""
    user_id: str = ""
    session_id: str = ""
    confidence: float = 1.0
    recency_weight: float = 1.0


@dataclass
class Proposal:
    """A validated write that is not yet in SQLite."""

    id: str
    type: RecordType
    key: str
    value: str
    source: str
    # ── scoping ──────────────────────────────────────────────────────
    workspace: str = ""
    user_id: str = ""
    session_id: str = ""
    confidence: float = 1.0


class MemoryStore:
    """User-facing memory API. Writes go through policy, then SQLite."""

    def __init__(
        self,
        db_path: Path,
        *,
        policy: MemoryPolicy | None = None,
        embedder: Embedder | None = None,
        privacy_profile: str = "fully_local",
        network_mode: str = "offline",
        enabled: bool = True,
        default_workspace: str = "",
        default_user: str = "",
        default_session: str = "",
    ) -> None:
        self.db_path = Path(db_path)
        self.policy = policy if policy is not None else MemoryPolicy()
        self.privacy_profile = privacy_profile
        self.network_mode = network_mode
        self._enabled = enabled
        self.default_workspace = default_workspace
        self.default_user = default_user
        self.default_session = default_session
        self._embeddings = EmbeddingService(
            embedder,
            privacy_profile=privacy_profile,
            network_mode=network_mode,
        )
        self._pending: dict[str, Proposal] = {}
        self._database: MemoryDatabase | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def propose(
        self,
        record: MemoryRecord,
        *,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        confidence: float | None = None,
    ) -> Proposal:
        """Validate a record and queue it. Does not open or write SQLite."""
        record_type = _coerce_type(record.type)
        key = record.key.strip()
        value = record.value
        source = record.source.strip()
        if not key or not source:
            raise MemoryStoreError(CODE_INVALID_RECORD)
        if not isinstance(value, str) or not value.strip():
            raise MemoryStoreError(CODE_INVALID_RECORD)
        self.policy.check(key, value)
        ws = workspace if workspace is not None else self.default_workspace
        uid = user_id if user_id is not None else self.default_user
        sid = session_id if session_id is not None else self.default_session
        conf = confidence if confidence is not None else record.confidence
        # Generate dedup hash
        dedup_hash = _make_hash(value.strip())
        proposal = Proposal(
            id=uuid4().hex,
            type=record_type,
            key=key,
            value=value,
            source=source,
            workspace=ws,
            user_id=uid,
            session_id=sid,
            confidence=conf,
        )
        self._pending[proposal.id] = proposal
        # Check for existing duplicate within the same scope
        self._check_duplicate_in_memory(proposal)
        return proposal

    def _check_duplicate_in_memory(self, proposal: Proposal) -> None:
        """Check for duplicates among in-memory pending proposals only."""
        for existing in self._pending.values():
            if existing.id == proposal.id:
                continue
            if existing.workspace != proposal.workspace:
                continue
            if existing.user_id != proposal.user_id:
                continue
            if existing.session_id and existing.session_id != proposal.session_id:
                continue
            if _value_match(existing.value, proposal.value):
                proposal.confidence = min(proposal.confidence, 0.5)
                break

    def _check_duplicate_in_db(self, proposal: Proposal) -> None:
        """Check for duplicates in the persisted database."""
        all_records = self._db().list(None)
        for row in all_records:
            if row.workspace != proposal.workspace:
                continue
            if row.user_id != proposal.user_id:
                continue
            if row.session_id and row.session_id != proposal.session_id:
                continue
            if _value_match(row.value, proposal.value):
                proposal.confidence = min(proposal.confidence, 0.5)
                break

    def commit(self, proposal_id: str) -> MemoryRecord | None:
        """Persist a pending proposal. No-op when memory is disabled."""
        proposal = self._pending.get(proposal_id)
        if proposal is None:
            raise MemoryStoreError(CODE_UNKNOWN_PROPOSAL)
        if not self._enabled:
            return None
        now = _now()
        record = MemoryRecord(
            id=proposal.id,
            type=proposal.type,
            key=proposal.key,
            value=proposal.value,
            source=proposal.source,
            created_at=now,
            updated_at=now,
            dedup_hash=_make_hash(proposal.value),
            workspace=proposal.workspace,
            user_id=proposal.user_id,
            session_id=proposal.session_id,
            confidence=proposal.confidence,
            recency_weight=1.0,
        )
        self._check_duplicate_in_db(proposal)
        self._db().insert(_to_row(record))
        del self._pending[proposal_id]
        self._embed_record(record)
        return record

    def list(
        self,
        record_type: RecordType | str | None = None,
        *,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        """List records with optional scope filters."""
        if record_type is None and workspace is None and user_id is None and session_id is None:
            return [_from_row(row) for row in self._db().list(None)]
        filtered_type = _coerce_type(record_type) if record_type is not None else None
        type_name = filtered_type.value if filtered_type is not None else None
        rows = self._db().list(type_name)
        ws = workspace if workspace is not None else self.default_workspace
        uid = user_id if user_id is not None else self.default_user
        sid = session_id if session_id is not None else self.default_session
        results = []
        for row in rows:
            if row.workspace != ws:
                continue
            if row.user_id != uid:
                continue
            if sid != "" and row.session_id != sid:
                continue
            results.append(_from_row(row))
        return results

    def get(self, record_id: str) -> MemoryRecord | None:
        row = self._db().get(record_id)
        if row is None:
            return None
        return _from_row(row)

    def update(
        self,
        record_id: str,
        *,
        key: str | None = None,
        value: str | None = None,
        record_type: RecordType | str | None = None,
        source: str | None = None,
        confidence: float | None = None,
    ) -> MemoryRecord | None:
        """Correct a stored record. No-op when memory is disabled."""
        if not self._enabled:
            return None
        existing = self.get(record_id)
        if existing is None:
            return None
        next_key = existing.key if key is None else key.strip()
        next_value = existing.value if value is None else value
        next_type = existing.type if record_type is None else _coerce_type(record_type)
        next_source = existing.source if source is None else source.strip()
        if not next_key or not next_source or not next_value.strip():
            raise MemoryStoreError(CODE_INVALID_RECORD)
        self.policy.check(next_key, next_value)
        next_conf = confidence if confidence is not None else existing.confidence
        updated = MemoryRecord(
            id=existing.id,
            type=next_type,
            key=next_key,
            value=next_value,
            source=next_source,
            created_at=existing.created_at,
            updated_at=_now(),
            dedup_hash=_make_hash(next_value) if value is not None else existing.dedup_hash,
            workspace=existing.workspace,
            user_id=existing.user_id,
            session_id=existing.session_id,
            confidence=next_conf,
            recency_weight=existing.recency_weight,
        )
        self._db().update(_to_row(updated))
        self._embed_record(updated)
        return updated

    def delete(self, record_id: str) -> bool:
        if not self._enabled:
            return False
        return self._db().delete(record_id)

    def clear_all(self) -> int:
        if not self._enabled:
            return 0
        return self._db().clear_all()

    def delete_scope(
        self,
        *,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        """Delete all records matching the scope filter. Returns count deleted."""
        ws = workspace if workspace is not None else self.default_workspace
        uid = user_id if user_id is not None else self.default_user
        sid = session_id if session_id is not None else self.default_session
        rows = self._db().list(None)
        deleted = 0
        for row in rows:
            if row.workspace != ws:
                continue
            if row.user_id != uid:
                continue
            if sid != "" and row.session_id != sid:
                continue
            self._db().delete(row.id)
            deleted += 1
        return deleted

    def delete_low_confidence(self, *, threshold: float = 0.3) -> int:
        """Delete records below confidence threshold. Returns count deleted."""
        if not self._enabled:
            return 0
        rows = self._db().list(None)
        deleted = 0
        for row in rows:
            conf = row.confidence if hasattr(row, "confidence") else 1.0
            if conf < threshold:
                self._db().delete(row.id)
                deleted += 1
        return deleted


    def export(self) -> dict[str, list[dict[str, object]]]:
        """Export all records grouped by type. Secret values are never included."""
        result: dict[str, list[dict[str, object]]] = {}
        for rec_type in RecordType:
            items = [
                {
                    "id": r.id,
                    "key": r.key,
                    "type": rec_type.value,
                    "value": r.value,
                    "source": r.source,
                    "workspace": r.workspace,
                    "user_id": r.user_id,
                    "session_id": r.session_id,
                    "confidence": r.confidence,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in self.list(rec_type)
            ]
            if items:
                result[rec_type.value] = items
        return result

    def inspect(
        self,
        *,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        record_type: RecordType | str | None = None,
    ) -> dict[str, int]:
        """Return counts scoped to filters. Keys: total, by_type, scopes."""
        if record_type is None and workspace is None and user_id is None and session_id is None:
            rows = self._db().list(None)
            counts: dict[str, int] = {"total": len(rows)}
            for row in rows:
                counts[row.type] = counts.get(row.type, 0) + 1
            counts["pending"] = len(self._pending)
            return counts
        filtered_type = _coerce_type(record_type) if record_type is not None else None
        type_name = filtered_type.value if filtered_type is not None else None
        rows = self._db().list(type_name)
        ws = workspace if workspace is not None else self.default_workspace
        uid = user_id if user_id is not None else self.default_user
        sid = session_id if session_id is not None else self.default_session
        filtered_rows: list[MemoryRow] = []
        for row in rows:
            if row.workspace != ws:
                continue
            if row.user_id != uid:
                continue
            if sid != "" and row.session_id != sid:
                continue
            filtered_rows.append(row)
        counts: dict[str, int] = {"total": len(filtered_rows)}
        for row in filtered_rows:
            counts[row.type] = counts.get(row.type, 0) + 1
        return counts
    def migrate_json(self, old: Mapping[str, object] | Path) -> MigrationStats:
        from mark.memory.migrations.json import migrate_json as _migrate

        return _migrate(old, self)

    def search(
        self,
        query: str,
        *,
        record_type: RecordType | str | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search: embed query, rank stored records, return top_k matches."""
        if not self._enabled:
            return []
        if self._embeddings.must_stay_local() and self._embeddings.embedder is None:
            return self._keyword_search(query, record_type=record_type, top_k=top_k)
        vector = self._embeddings.embed(query)
        if vector is None:
            return self._keyword_search(query, record_type=record_type, top_k=top_k)
        filtered_type = _coerce_type(record_type) if record_type is not None else None
        type_name = filtered_type.value if filtered_type is not None else ""
        results = self._db().find_similar(vector, top_k=top_k)
        ws = workspace if workspace is not None else self.default_workspace
        uid = user_id if user_id is not None else self.default_user
        sid = session_id if session_id is not None else self.default_session
        final: list[MemoryRecord] = []
        for r in results:
            if r.workspace != ws:
                continue
            if r.user_id != uid:
                continue
            if sid != "" and r.session_id != sid:
                continue
            if type_name and r.type != type_name:
                continue
            if min_score > 0.0:
                if not hasattr(r, "_similarity") or r._similarity < min_score:  # type: ignore[attr-defined]
                    continue
            final.append(_from_row(r))
        return final

    def _keyword_search(
        self,
        query: str,
        *,
        record_type: RecordType | str | None = None,
        top_k: int = 5,
    ) -> list[MemoryRecord]:
        """Fallback: simple keyword matching on key/value."""
        q = query.lower()
        all_records = self.list(record_type)
        scored: list[tuple[MemoryRecord, int]] = []
        for rec in all_records:
            score = 0
            if q in rec.key.lower():
                score += 3
            if q in rec.value.lower():
                score += 1
            for word in q.split():
                if word in rec.key.lower():
                    score += 1
                if word in rec.value.lower():
                    score += 1
            if score > 0:
                scored.append((rec, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scored[:top_k]]

    def close(self) -> None:
        if self._database is not None:
            self._database.close()
            self._database = None

    def _db(self) -> MemoryDatabase:
        if self._database is None:
            self._database = MemoryDatabase(self.db_path)
        return self._database

    def _embed_record(self, record: MemoryRecord) -> None:
        vector = self._embeddings.embed(record.value)
        if vector is None:
            return
        self._db().upsert_embedding(record.id, vector)


# ── helpers ───────────────────────────────────────────────────────────

import hashlib


@dataclass(frozen=True)
class MigrationStats:
    """How many legacy entries were written or skipped."""

    migrated: int
    skipped_secrets: int
    skipped_empty: int
    by_legacy_category: dict[str, int]
    by_type: dict[str, int]


def _coerce_type(value: RecordType | str) -> RecordType:
    if isinstance(value, RecordType):
        return value
    try:
        return RecordType(value)
    except ValueError:
        raise MemoryStoreError(CODE_UNKNOWN_TYPE) from None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _value_match(a: str, b: str, *, threshold: float = 0.9) -> bool:
    """Quick near-equal check for deduplication."""
    if a.lower().strip() == b.lower().strip():
        return True
    aw = set(a.lower().split())
    bw = set(b.lower().split())
    if not aw or not bw:
        return False
    overlap = len(aw & bw) / min(len(aw), len(bw))
    return overlap >= threshold


def _to_row(record: MemoryRecord) -> MemoryRow:
    return MemoryRow(
        id=record.id,
        type=record.type.value,
        key=record.key,
        value=record.value,
        source=record.source,
        created_at=record.created_at,
        updated_at=record.updated_at,
        dedup_hash=record.dedup_hash,
        workspace=record.workspace,
        user_id=record.user_id,
        session_id=record.session_id,
        confidence=record.confidence,
        recency_weight=record.recency_weight,
    )


def _from_row(row: MemoryRow) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        type=_coerce_type(row.type),
        key=row.key,
        value=row.value,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
        dedup_hash=getattr(row, "dedup_hash", ""),
        workspace=getattr(row, "workspace", ""),
        user_id=getattr(row, "user_id", ""),
        session_id=getattr(row, "session_id", ""),
        confidence=getattr(row, "confidence", 1.0),
        recency_weight=getattr(row, "recency_weight", 1.0),
    )


__all__ = [
    "MemoryRecord",
    "MemoryStore",
    "MigrationStats",
    "Proposal",
    "RecordType",
]


# ── Simple async wrapper for E2E tests ──────────────────────────────────

import asyncio
import json
import sqlite3
import uuid


class MemoryRepository:
    """Minimal async SQLite-backed memory repository for E2E tests."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_records (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL DEFAULT '',
                metadata TEXT,
                type TEXT NOT NULL DEFAULT 'text',
                key TEXT NOT NULL DEFAULT '_default_',
                value TEXT NOT NULL DEFAULT '1',
                source TEXT NOT NULL DEFAULT 'e2e_test',
                workspace TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 1.0,
                recency_weight REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00'))
            )
        """)
        # Add metadata column if missing (from older schema)
        try:
            conn.execute("ALTER TABLE memory_records ADD COLUMN metadata TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()

    async def insert(self, *, content: str, metadata: dict[str, str] | None = None) -> str:
        loop = asyncio.get_running_loop()
        doc_id = uuid.uuid4().hex
        meta_json = json.dumps(metadata) if metadata else "{}"

        def _insert():
            conn = sqlite3.connect(str(self._db_path))
            try:
                self._init_db(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO memory_records (id, content, metadata, type, key, value, source, workspace, user_id, session_id, confidence, recency_weight, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%S+00:00'), strftime('%Y-%m-%dT%H:%M:%S+00:00'))",
                    (doc_id, content, meta_json, 'text', '_default_', '1', 'e2e_test', '', '', '', 1.0, 1.0))
                conn.commit()
            finally:
                conn.close()

        await loop.run_in_executor(None, _insert)
        return doc_id

    async def get(self, doc_id: str) -> dict[str, str] | None:
        db_path = str(self._db_path)

        def _get() -> dict[str, str] | None:
            conn = sqlite3.connect(db_path)
            try:
                self._init_db(conn)
                row = conn.execute(
                    "SELECT content, metadata FROM memory_records WHERE id = ?", (doc_id,)).fetchone()
                if row is None:
                    return None
                return {"content": row[0], "metadata": json.loads(row[1])}
            finally:
                conn.close()

        return await asyncio.get_running_loop().run_in_executor(None, _get)


    async def search(self, query: str, *, top_k: int = 5) -> list[dict[str, str]]:
        """Simple keyword search over memory_records.content. Tokenises query on whitespace
        and requires ALL tokens to be present (LIKE %token% per word)."""
        import sqlite3
        db_path = str(self._db_path)
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []
        conditions = " AND ".join(["content LIKE ?" for _ in tokens])
        params = tuple(f"%{t}%" for t in tokens)
        conn = sqlite3.connect(db_path)
        try:
            self._init_db(conn)
            rows = conn.execute(
                f"SELECT id, content, metadata FROM memory_records WHERE {conditions}",
                params).fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r[0],
                    "content": r[1],
                    "metadata": r[2],
                })
            return results[:top_k]
        finally:
            conn.close()

    async def close(self) -> None:
        """Close any underlying connections."""
        pass



