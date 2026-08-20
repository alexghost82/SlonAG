"""Transactional SQLite migrations for the Session Engine."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

_V1 = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    context_state TEXT NOT NULL,
    memory_scope TEXT NOT NULL,
    permissions_profile TEXT NOT NULL
);
CREATE INDEX idx_sessions_workspace_updated ON sessions(workspace_id, updated_at);
CREATE INDEX idx_sessions_title ON sessions(title);
CREATE TABLE transcript_entries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT,
    text TEXT,
    tool_call_id TEXT,
    tool_name TEXT,
    data TEXT,
    artifacts TEXT NOT NULL,
    media_references TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);
CREATE INDEX idx_transcript_session_turn ON transcript_entries(session_id, turn_id, sequence);
CREATE TABLE session_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    effective_provider_id TEXT,
    effective_model_id TEXT
);
CREATE INDEX idx_runs_session_status ON session_runs(session_id, status);
"""


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS session_schema(version INTEGER NOT NULL)")
    row = connection.execute("SELECT version FROM session_schema LIMIT 1").fetchone()
    version = 0 if row is None else int(row[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"unsupported session schema version: {version}")
    if version < 1:
        for statement in _V1.split(";"):
            if statement.strip():
                connection.execute(statement)
        connection.execute("DELETE FROM session_schema")
        connection.execute("INSERT INTO session_schema(version) VALUES (1)")


__all__ = ["SCHEMA_VERSION", "migrate"]
