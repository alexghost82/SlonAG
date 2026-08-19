"""SQLite schema for the memory store. stdlib sqlite3 only."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

_RECORDS_SQL = """
CREATE TABLE IF NOT EXISTS memory_records (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_EMBEDDINGS_SQL = """
CREATE TABLE IF NOT EXISTS memory_embeddings (
    record_id TEXT PRIMARY KEY,
    vector TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES memory_records(id) ON DELETE CASCADE
)
"""

_META_SQL = """
CREATE TABLE IF NOT EXISTS memory_schema (
    version INTEGER NOT NULL
)
"""


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create tables and record the schema version when the file is new."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(_RECORDS_SQL)
    connection.execute(_EMBEDDINGS_SQL)
    connection.execute(_META_SQL)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_records_type ON memory_records(type)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_records_key ON memory_records(key)"
    )
    row = connection.execute("SELECT version FROM memory_schema LIMIT 1").fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO memory_schema (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
    connection.commit()


__all__ = ["SCHEMA_VERSION", "apply_schema"]
