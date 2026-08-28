"""SQLite schema for the memory store. stdlib sqlite3 only.

Schema history:
  v1 — baseline (records + embeddings + meta)
  v2 — workspace/user/session scoping, dedup hash, confidence, recency
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4

_RECORDS_SQL = """
CREATE TABLE IF NOT EXISTS memory_records (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL DEFAULT '',
    type         TEXT NOT NULL DEFAULT 'text',
    key          TEXT NOT NULL DEFAULT '_default_',
    value        TEXT NOT NULL DEFAULT '1',
    source       TEXT NOT NULL DEFAULT 'e2e_test',
    dedup_hash   TEXT,
    workspace    TEXT NOT NULL DEFAULT '',
    user_id      TEXT NOT NULL DEFAULT '',
    session_id   TEXT NOT NULL DEFAULT '',
    confidence   REAL NOT NULL DEFAULT 1.0,
    recency_weight REAL NOT NULL DEFAULT 1.0,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00'))
)
"""

_EMBEDDINGS_SQL = """
CREATE TABLE IF NOT EXISTS memory_embeddings (
    record_id TEXT PRIMARY KEY,
    vector    TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES memory_records(id) ON DELETE CASCADE
)
"""

_META_SQL = """
CREATE TABLE IF NOT EXISTS memory_schema (
    version INTEGER NOT NULL
)
"""

# ── v2 migration: add scoped columns ──────────────────────────────────
_V2_ADD = [
    "ALTER TABLE memory_records ADD COLUMN dedup_hash TEXT",
    "ALTER TABLE memory_records ADD COLUMN workspace TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE memory_records ADD COLUMN user_id   TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE memory_records ADD COLUMN session_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE memory_records ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE memory_records ADD COLUMN recency_weight REAL NOT NULL DEFAULT 1.0",
]

# ── v3 migration: add content column (used by memory repo insert) ──
_V3_ADD = [
    "ALTER TABLE memory_records ADD COLUMN content TEXT NOT NULL DEFAULT ''",
]


# ── v4 migration: add metadata column (used by memory repo insert) ──
_V4_ADD = [
    "ALTER TABLE memory_records ADD COLUMN metadata TEXT",
]


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
    # Scoped indexes
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_records_workspace "
        "ON memory_records(workspace)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_records_user "
        "ON memory_records(user_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_records_session "
        "ON memory_records(session_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_records_dedup "
        "ON memory_records(dedup_hash) WHERE dedup_hash IS NOT NULL"
    )
    row = connection.execute("SELECT version FROM memory_schema LIMIT 1").fetchone()
    if row is None:
        # New DB: start at version 1 so v2/v3/v4 migrations run below
        connection.execute(
            "INSERT INTO memory_schema (version) VALUES (?)",
            (1,),
        )
        connection.commit()
        current_version = 1  # fall through to migration blocks
    else:
        current_version = row["version"]
    if current_version < 2:
        _run_migrations(connection)
    if current_version < 3:
        for stmt in _V3_ADD:
            try:
                connection.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already added
        connection.execute(
            "UPDATE memory_schema SET version = ?", (3,)
        )
        connection.commit()
    if current_version < 4:
        for stmt in _V4_ADD:
            try:
                connection.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already added
        connection.execute(
            "UPDATE memory_schema SET version = ?", (4,)
        )
        connection.commit()


def _run_migrations(connection: sqlite3.Connection) -> None:
    """Add v2 columns if they don't already exist (idempotent)."""
    for stmt in _V2_ADD:
        try:
            connection.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already added (partial migration, retry-safe)
    connection.execute(
        "UPDATE memory_schema SET version = ?", (2,)
    )
    connection.commit()


__all__ = ["SCHEMA_VERSION", "apply_schema"]
