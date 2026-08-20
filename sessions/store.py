"""SQLite persistence for logical sessions and ordered transcripts."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sessions.contracts import (
    ModelPolicy,
    RunStatus,
    Session,
    SessionRun,
    SessionStatus,
    TranscriptEntry,
    TranscriptKind,
    TranscriptState,
)
from sessions.migrations import migrate


class SessionStoreError(RuntimeError):
    pass


class SessionCorruptionError(SessionStoreError):
    def __init__(self, backup_path: Path) -> None:
        super().__init__(f"session database is corrupt; preserved at {backup_path.name}")
        self.backup_path = backup_path


class SessionInactiveError(SessionStoreError):
    pass


class SessionStore:
    """One transaction-safe SQLite store at an injected path."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self._connection = sqlite3.connect(
                self.path, check_same_thread=False, isolation_level=None
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            check = self._connection.execute("PRAGMA quick_check").fetchone()
            if check is None or str(check[0]).lower() != "ok":
                raise sqlite3.DatabaseError("integrity check failed")
            with self.transaction():
                migrate(self._connection)
        except sqlite3.DatabaseError as exc:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            backup_path = self._preserve_corrupt_files()
            raise SessionCorruptionError(backup_path) from exc
        except RuntimeError as exc:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            raise SessionStoreError(str(exc)) from exc

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def backup(self, target: str | Path) -> Path:
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = target_path.with_suffix(target_path.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        try:
            with self._lock:
                destination = sqlite3.connect(temporary)
                try:
                    self._connection.backup(destination)
                    if not _backup_is_valid(destination):
                        raise SessionStoreError("session backup integrity check failed")
                finally:
                    destination.close()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(target_path)
        return target_path

    def insert_session(self, session: Session) -> None:
        with self.transaction():
            self._connection.execute(
                """INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id, session.created_at, session.updated_at, session.title,
                    session.agent_id, session.model_policy.provider_id,
                    session.model_policy.model_id, session.workspace_id,
                    session.status.value, _json(session.context_state),
                    session.memory_scope, session.permissions_profile,
                ),
            )

    def get_session(self, session_id: str, *, workspace_id: str) -> Session | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM sessions WHERE id = ? AND workspace_id = ?",
                (session_id, workspace_id),
            ).fetchone()
        return None if row is None else self._session_from_row(row)

    def get_session_unhydrated(self, session_id: str) -> Session | None:
        """Read lifecycle metadata without recursively loading transcript/runs."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return Session(
            id=str(row["id"]), created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]), title=str(row["title"]),
            agent_id=str(row["agent_id"]),
            model_policy=ModelPolicy(str(row["provider_id"]), str(row["model_id"])),
            workspace_id=str(row["workspace_id"]),
            status=SessionStatus(str(row["status"])),
            context_state=json.loads(str(row["context_state"])),
            memory_scope=str(row["memory_scope"]),
            permissions_profile=str(row["permissions_profile"]),
        )

    def list_sessions(
        self, *, workspace_id: str, query: str | None = None
    ) -> list[Session]:
        sql = "SELECT * FROM sessions WHERE workspace_id = ?"
        values: list[object] = [workspace_id]
        if query:
            sql += " AND title LIKE ? ESCAPE '\\'"
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{escaped}%")
        sql += " ORDER BY updated_at DESC, id ASC"
        with self._lock:
            rows = self._connection.execute(sql, values).fetchall()
        return [self._session_from_row(row) for row in rows]

    def update_status(
        self,
        session_id: str,
        *,
        workspace_id: str,
        status: SessionStatus,
        updated_at: str,
    ) -> bool:
        with self.transaction():
            cursor = self._connection.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
                (status.value, updated_at, session_id, workspace_id),
            )
        return cursor.rowcount > 0

    def resume_session(
        self, session_id: str, *, workspace_id: str, updated_at: str
    ) -> bool:
        with self.transaction():
            cursor = self._connection.execute(
                """UPDATE sessions SET status = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ? AND status = ?""",
                (SessionStatus.ACTIVE.value, updated_at, session_id, workspace_id,
                 SessionStatus.CLOSED.value),
            )
        return cursor.rowcount > 0

    def archive_session(
        self, session_id: str, *, workspace_id: str, updated_at: str
    ) -> bool:
        with self.transaction():
            active = self._connection.execute(
                """SELECT 1 FROM session_runs
                WHERE session_id = ? AND status = ? LIMIT 1""",
                (session_id, RunStatus.ACTIVE.value),
            ).fetchone()
            if active is not None:
                raise SessionInactiveError("session has active runs")
            cursor = self._connection.execute(
                """UPDATE sessions SET status = ?, updated_at = ?
                WHERE id = ? AND workspace_id = ? AND status IN (?, ?)""",
                (SessionStatus.ARCHIVED.value, updated_at, session_id, workspace_id,
                 SessionStatus.ACTIVE.value, SessionStatus.CLOSED.value),
            )
        return cursor.rowcount > 0

    def close_session(
        self, session_id: str, *, workspace_id: str, updated_at: str
    ) -> bool:
        with self.transaction():
            row = self._connection.execute(
                "SELECT status FROM sessions WHERE id = ? AND workspace_id = ?",
                (session_id, workspace_id),
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            current = SessionStatus(str(row["status"]))
            if current is SessionStatus.CLOSED:
                return False
            if current is not SessionStatus.ACTIVE:
                raise SessionInactiveError("session is not active")
            self._connection.execute(
                "UPDATE session_runs SET status = ?, updated_at = ? WHERE session_id = ? AND status = ?",
                (RunStatus.CANCELLED.value, updated_at, session_id, RunStatus.ACTIVE.value),
            )
            self._connection.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (SessionStatus.CLOSED.value, updated_at, session_id),
            )
        return True

    def delete_session(self, session_id: str, *, workspace_id: str) -> bool:
        with self.transaction():
            cursor = self._connection.execute(
                """DELETE FROM sessions
                WHERE id = ? AND workspace_id = ? AND status = ?""",
                (session_id, workspace_id, SessionStatus.ARCHIVED.value),
            )
        return cursor.rowcount > 0

    def append_entry(self, entry: TranscriptEntry, *, workspace_id: str) -> TranscriptEntry:
        with self.transaction():
            owner = self._connection.execute(
                "SELECT status FROM sessions WHERE id = ? AND workspace_id = ?",
                (entry.session_id, workspace_id),
            ).fetchone()
            if owner is None:
                raise KeyError(entry.session_id)
            if str(owner["status"]) != SessionStatus.ACTIVE.value:
                raise SessionInactiveError("session is not active")
            if (
                entry.tool_call_id
                and entry.kind in (TranscriptKind.TOOL_CALL, TranscriptKind.TOOL_RESULT)
            ):
                existing = self._connection.execute(
                    """SELECT * FROM transcript_entries
                    WHERE session_id = ? AND kind = ? AND tool_call_id = ?
                    LIMIT 1""",
                    (entry.session_id, entry.kind.value, entry.tool_call_id),
                ).fetchone()
                if existing is not None:
                    return _entry_from_row(existing)
            sequence = int(self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM transcript_entries WHERE session_id = ?",
                (entry.session_id,),
            ).fetchone()[0])
            stored = TranscriptEntry(**{**entry.__dict__, "sequence": sequence})
            self._connection.execute(
                """INSERT INTO transcript_entries
                (id, session_id, turn_id, sequence, kind, state, created_at, role,
                 text, tool_call_id, tool_name, data, artifacts, media_references)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stored.id, stored.session_id, stored.turn_id, stored.sequence,
                    stored.kind.value, stored.state.value, stored.created_at,
                    stored.role, stored.text, stored.tool_call_id, stored.tool_name,
                    _json(stored.data), _json(stored.artifacts),
                    _json(stored.media_references),
                ),
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (stored.created_at, stored.session_id),
            )
        return stored

    def list_entries(self, session_id: str, *, workspace_id: str) -> list[TranscriptEntry]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT transcript_entries.* FROM transcript_entries
                JOIN sessions ON sessions.id = transcript_entries.session_id
                WHERE transcript_entries.session_id = ? AND sessions.workspace_id = ?
                ORDER BY transcript_entries.sequence ASC""",
                (session_id, workspace_id),
            ).fetchall()
        return [_entry_from_row(row) for row in rows]

    def insert_run(self, run: SessionRun, *, workspace_id: str) -> None:
        with self.transaction():
            owner = self._connection.execute(
                "SELECT status FROM sessions WHERE id = ? AND workspace_id = ?",
                (run.session_id, workspace_id),
            ).fetchone()
            if owner is None:
                raise KeyError(run.session_id)
            if str(owner["status"]) != SessionStatus.ACTIVE.value:
                raise SessionInactiveError("session is not active")
            self._connection.execute(
                "INSERT INTO session_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.session_id, run.turn_id, run.status.value,
                 run.started_at, run.updated_at, run.effective_provider_id,
                 run.effective_model_id),
            )

    def update_run_status(self, run_id: str, status: RunStatus, updated_at: str) -> bool:
        with self.transaction():
            row = self._connection.execute(
                "SELECT status FROM session_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return False
            current = RunStatus(str(row["status"]))
            if current is status:
                return True
            if current is not RunStatus.ACTIVE:
                return False
            cursor = self._connection.execute(
                """UPDATE session_runs SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?""",
                (status.value, updated_at, run_id, RunStatus.ACTIVE.value),
            )
        return cursor.rowcount > 0

    def update_run_effective_model(
        self, run_id: str, provider_id: str, model_id: str, updated_at: str
    ) -> bool:
        with self.transaction():
            cursor = self._connection.execute(
                """UPDATE session_runs
                SET effective_provider_id = ?, effective_model_id = ?, updated_at = ?
                WHERE id = ?""",
                (provider_id, model_id, updated_at, run_id),
            )
        return cursor.rowcount > 0

    def active_runs(self, session_id: str, *, workspace_id: str) -> list[SessionRun]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT session_runs.* FROM session_runs
                JOIN sessions ON sessions.id = session_runs.session_id
                WHERE session_runs.session_id = ? AND sessions.workspace_id = ?
                  AND session_runs.status = ? ORDER BY session_runs.started_at""",
                (session_id, workspace_id, RunStatus.ACTIVE.value),
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def recover_interrupted(self, updated_at: str) -> int:
        with self.transaction():
            runs = self._connection.execute(
                "UPDATE session_runs SET status = ?, updated_at = ? WHERE status = ?",
                (RunStatus.INTERRUPTED.value, updated_at, RunStatus.ACTIVE.value),
            ).rowcount
            self._connection.execute(
                "UPDATE transcript_entries SET state = ? WHERE state = ?",
                (TranscriptState.INTERRUPTED.value, TranscriptState.STREAMING.value),
            )
        return runs

    def _session_from_row(self, row: sqlite3.Row) -> Session:
        workspace_id = str(row["workspace_id"])
        session_id = str(row["id"])
        return Session(
            id=session_id, created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]), title=str(row["title"]),
            agent_id=str(row["agent_id"]),
            model_policy=ModelPolicy(str(row["provider_id"]), str(row["model_id"])),
            workspace_id=workspace_id, status=SessionStatus(str(row["status"])),
            transcript=tuple(self.list_entries(session_id, workspace_id=workspace_id)),
            context_state=json.loads(str(row["context_state"])),
            memory_scope=str(row["memory_scope"]),
            permissions_profile=str(row["permissions_profile"]),
            active_runs=tuple(self.active_runs(session_id, workspace_id=workspace_id)),
        )

    def _preserve_corrupt_files(self) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}.bak")
        if self.path.exists():
            shutil.copy2(self.path, target)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists():
                    shutil.copy2(sidecar, Path(str(target) + suffix))
        return target


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _backup_is_valid(connection: sqlite3.Connection) -> bool:
    checks = connection.execute("PRAGMA integrity_check").fetchall()
    return bool(checks) and all(str(row[0]).lower() == "ok" for row in checks)


def _entry_from_row(row: sqlite3.Row) -> TranscriptEntry:
    return TranscriptEntry(
        id=str(row["id"]), session_id=str(row["session_id"]),
        turn_id=str(row["turn_id"]), sequence=int(row["sequence"]),
        kind=TranscriptKind(str(row["kind"])), state=TranscriptState(str(row["state"])),
        created_at=str(row["created_at"]), role=row["role"], text=row["text"],
        tool_call_id=row["tool_call_id"], tool_name=row["tool_name"],
        data=json.loads(str(row["data"])),
        artifacts=tuple(json.loads(str(row["artifacts"]))),
        media_references=tuple(json.loads(str(row["media_references"]))),
    )


def _run_from_row(row: sqlite3.Row) -> SessionRun:
    return SessionRun(
        id=str(row["id"]), session_id=str(row["session_id"]),
        turn_id=str(row["turn_id"]), status=RunStatus(str(row["status"])),
        started_at=str(row["started_at"]), updated_at=str(row["updated_at"]),
        effective_provider_id=row["effective_provider_id"],
        effective_model_id=row["effective_model_id"],
    )


__all__ = [
    "SessionCorruptionError", "SessionInactiveError", "SessionStore",
    "SessionStoreError",
]
