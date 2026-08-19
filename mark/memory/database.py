"""SQLite access for memory records. Callers inject the database path."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mark.memory.migrations.schema import apply_schema


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
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO memory_records
                    (id, type, key, value, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    row.type,
                    row.key,
                    row.value,
                    row.source,
                    row.created_at,
                    row.updated_at,
                ),
            )

    def get(self, record_id: str) -> MemoryRow | None:
        cursor = self._connection.execute(
            """
            SELECT id, type, key, value, source, created_at, updated_at
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
                SELECT id, type, key, value, source, created_at, updated_at
                FROM memory_records
                ORDER BY created_at ASC, key ASC
                """
            )
        else:
            cursor = self._connection.execute(
                """
                SELECT id, type, key, value, source, created_at, updated_at
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
                SET type = ?, key = ?, value = ?, source = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    row.type,
                    row.key,
                    row.value,
                    row.source,
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


def _row_from_sql(row: sqlite3.Row) -> MemoryRow:
    return MemoryRow(
        id=str(row["id"]),
        type=str(row["type"]),
        key=str(row["key"]),
        value=str(row["value"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


__all__ = ["MemoryDatabase", "MemoryRow"]
