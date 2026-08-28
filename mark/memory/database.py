"""SQLite access for memory records. Callers inject the database path."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mark.memory.migrations.schema import SCHEMA_VERSION, apply_schema


@dataclass(frozen=True)
class MemoryRow:
    """One persisted row. Mapping to ``MemoryRecord`` happens in the store."""

    id: str
    type: str
    key: str
    value: str
    source: str
    created_at: str
    updated_at: str
    # ── v2+ scoped fields ─────────────────────────────────────────────
    dedup_hash: str = ""
    workspace: str = ""
    user_id: str = ""
    session_id: str = ""
    confidence: float = 1.0
    recency_weight: float = 1.0


class MemoryDatabase:
    """Own a sqlite3 connection at an injected path. Never touches JSON files."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        apply_schema(self._connection)

    def close(self) -> None:
        self._connection.close()

    def insert(self, row: MemoryRow) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO memory_records
                        (id, type, key, value, source, dedup_hash, workspace,
                         user_id, session_id, confidence, recency_weight,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.id,
                        row.type,
                        row.key,
                        row.value,
                        row.source,
                        getattr(row, "dedup_hash", None),
                        getattr(row, "workspace", ""),
                        getattr(row, "user_id", ""),
                        getattr(row, "session_id", ""),
                        getattr(row, "confidence", 1.0),
                        getattr(row, "recency_weight", 1.0),
                        row.created_at,
                        row.updated_at,
                    ),
                )
        except sqlite3.OperationalError:
            # Schema not yet updated — re-apply
            apply_schema(self._connection)
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO memory_records
                        (id, type, key, value, source, dedup_hash, workspace,
                         user_id, session_id, confidence, recency_weight,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.id,
                        row.type,
                        row.key,
                        row.value,
                        row.source,
                        getattr(row, "dedup_hash", None),
                        getattr(row, "workspace", ""),
                        getattr(row, "user_id", ""),
                        getattr(row, "session_id", ""),
                        getattr(row, "confidence", 1.0),
                        getattr(row, "recency_weight", 1.0),
                        row.created_at,
                        row.updated_at,
                    ),
                )

    def get(self, record_id: str) -> MemoryRow | None:
        cursor = self._connection.execute(
            """
            SELECT id, type, key, value, source, dedup_hash, workspace,
                   user_id, session_id, confidence, recency_weight,
                   created_at, updated_at
            FROM memory_records
            WHERE id = ?
            """,
            (record_id,),
        )
        fetched = cursor.fetchone()
        if fetched is None:
            return None
        return _row_from_sql(fetched)

    def list(self, record_type: str | None = None) -> list[MemoryRow]:
        if record_type is None:
            cursor = self._connection.execute(
                """
                SELECT id, type, key, value, source, dedup_hash, workspace,
                       user_id, session_id, confidence, recency_weight,
                       created_at, updated_at
                FROM memory_records
                ORDER BY created_at ASC, key ASC
                """
            )
        else:
            cursor = self._connection.execute(
                """
                SELECT id, type, key, value, source, dedup_hash, workspace,
                       user_id, session_id, confidence, recency_weight,
                       created_at, updated_at
                FROM memory_records
                WHERE type = ?
                ORDER BY created_at ASC, key ASC
                """,
                (record_type,),
            )
        return [_row_from_sql(item) for item in cursor.fetchall()]

    def update(self, row: MemoryRow) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE memory_records
                SET type = ?, key = ?, value = ?, source = ?, dedup_hash = ?,
                    workspace = ?, user_id = ?, session_id = ?,
                    confidence = ?, recency_weight = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    row.type,
                    row.key,
                    row.value,
                    row.source,
                    getattr(row, "dedup_hash", None),
                    getattr(row, "workspace", ""),
                    getattr(row, "user_id", ""),
                    getattr(row, "session_id", ""),
                    getattr(row, "confidence", 1.0),
                    getattr(row, "recency_weight", 1.0),
                    row.updated_at,
                    row.id,
                ),
            )
        return cursor.rowcount > 0

    def delete(self, record_id: str) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM memory_records WHERE id = ?",
                (record_id,),
            )
        return cursor.rowcount > 0

    def clear_all(self) -> int:
        with self._connection:
            cursor = self._connection.execute("DELETE FROM memory_records")
        return cursor.rowcount

    def upsert_embedding(self, record_id: str, vector: Sequence[float]) -> None:
        payload = json.dumps([float(item) for item in vector])
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO memory_embeddings (record_id, vector)
                VALUES (?, ?)
                ON CONFLICT(record_id) DO UPDATE SET vector = excluded.vector
                """,
                (record_id, payload),
            )

    def find_similar(
        self, vector: Sequence[float], *, top_k: int = 5
    ) -> list[MemoryRow]:
        """Return rows ranked by cosine similarity to the query vector.
        Each returned MemoryRow gets a transient _similarity attribute."""
        rows = self._connection.execute(
            """
            SELECT r.id, r.type, r.key, r.value, r.source, r.dedup_hash,
                   r.workspace, r.user_id, r.session_id, r.confidence,
                   r.recency_weight, r.created_at, r.updated_at
            FROM memory_records r
            JOIN memory_embeddings e ON r.id = e.record_id
            """
        ).fetchall()
        if not rows:
            return []
        scored: list[tuple[MemoryRow, float]] = []
        for row in rows:
            sql_row = _row_from_sql(row)
            stored = json.loads(row["vector"])
            sim = _cosine_similarity(vector, stored)
            scored.append((sql_row, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        results: list[MemoryRow] = []
        for sql_row, sim in scored[:top_k]:
            sql_row._similarity = sim  # type: ignore[attr-defined]
            results.append(sql_row)
        return results


def _row_from_sql(row: sqlite3.Row) -> MemoryRow:
    return MemoryRow(
        id=str(row["id"]),
        type=str(row["type"]),
        key=str(row["key"]),
        value=str(row["value"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        dedup_hash=str(row.get("dedup_hash", "") or ""),
        workspace=str(row.get("workspace", "") or ""),
        user_id=str(row.get("user_id", "") or ""),
        session_id=str(row.get("session_id", "") or ""),
        confidence=float(row.get("confidence", 1.0) or 1.0),
        recency_weight=float(row.get("recency_weight", 1.0) or 1.0),
    )


__all__ = ["MemoryDatabase", "MemoryRow"]


def _dot_product(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _magnitude(v: list[float]) -> float:
    import math

    return math.sqrt(sum(x * x for x in v))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    mag_a = _magnitude(a)
    mag_b = _magnitude(b)
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return _dot_product(a, b) / (mag_a * mag_b)


def init_db(db_path: str | Path) -> None:
    """Create the database file and apply the schema."""
    db = MemoryDatabase(Path(db_path))
    db.close()
