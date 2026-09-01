"""Transactional durable state owned by the Gateway bounded context."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 4


class GatewayStoreError(RuntimeError):
    pass


class GatewayStore:
    def __init__(self, path: str | Path, *, event_retention: int = 10_000) -> None:
        if event_retention <= 0:
            raise ValueError("event_retention must be positive")
        self.path = Path(path)
        self.event_retention = event_retention
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA journal_mode=WAL")
        with self.transaction():
            self._migrate()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    def _migrate(self) -> None:
        self._db.execute("CREATE TABLE IF NOT EXISTS gateway_schema(version INTEGER NOT NULL)")
        row = self._db.execute("SELECT version FROM gateway_schema LIMIT 1").fetchone()
        version = 0 if row is None else int(row[0])
        if version > SCHEMA_VERSION:
            raise GatewayStoreError(f"unsupported gateway schema version: {version}")
        if version == 0:
            schema = """
            CREATE TABLE trusted_devices(
              device_id TEXT PRIMARY KEY, device_name TEXT NOT NULL,
              public_key TEXT NOT NULL, key_fingerprint TEXT NOT NULL UNIQUE,
              workspace_id TEXT NOT NULL, active INTEGER NOT NULL,
              created_at REAL NOT NULL, revoked_at REAL
            );
            CREATE TABLE device_sessions(
              connection_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
              connected_at REAL NOT NULL, disconnected_at REAL,
              FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
            );
            CREATE TABLE gateway_events(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
              session_id TEXT, envelope_json TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE INDEX idx_gateway_events_scope ON gateway_events(workspace_id,sequence);
            CREATE TABLE replay_cursors(
              device_id TEXT NOT NULL, stream TEXT NOT NULL, sequence INTEGER NOT NULL,
              updated_at REAL NOT NULL, PRIMARY KEY(device_id,stream),
              FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
            );
            CREATE TABLE gateway_operations(
              operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, device_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL, session_id TEXT, status TEXT NOT NULL,
              payload_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
              FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
            );
            CREATE TABLE request_results(
              device_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
              request_id TEXT NOT NULL, response_json TEXT,
              status TEXT NOT NULL, created_at REAL NOT NULL,
              PRIMARY KEY(device_id,workspace_id,request_id)
            );
            CREATE TABLE artifact_grants(
              grant_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, device_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL, operation TEXT NOT NULL, mime_type TEXT NOT NULL,
              max_bytes INTEGER NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL,
              storage_name TEXT NOT NULL,
              FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
            );
            CREATE TABLE artifacts(
              artifact_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL, mime_type TEXT NOT NULL,
              size INTEGER NOT NULL, sha256 TEXT NOT NULL, storage_name TEXT NOT NULL,
              created_at REAL NOT NULL,
              FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
            );
            CREATE TABLE gateway_refresh_tokens(
              token_hash TEXT PRIMARY KEY, device_id TEXT NOT NULL,
              device_name TEXT, expires_at REAL NOT NULL, scopes_json TEXT NOT NULL,
              FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
            );
            CREATE TABLE used_access_jtis(
              jti TEXT PRIMARY KEY, used_at REAL NOT NULL
            );
            CREATE TABLE gateway_approvals(
              approval_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
              session_id TEXT, run_id TEXT, tool_call_id TEXT, tool_name TEXT NOT NULL,
              status TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL,
              expires_at REAL NOT NULL, decided_at REAL, decision_device_id TEXT
            );
            CREATE TABLE gateway_runtime_status(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              instance_id TEXT NOT NULL, state TEXT NOT NULL, heartbeat_at REAL NOT NULL,
              bind_host TEXT NOT NULL, tls_active INTEGER NOT NULL,
              connected_devices INTEGER NOT NULL, error_code TEXT
            );
            """
            for statement in schema.split(";"):
                if statement.strip():
                    self._db.execute(statement)
            self._db.execute("DELETE FROM gateway_schema")
            self._db.execute("INSERT INTO gateway_schema VALUES (?)", (SCHEMA_VERSION,))
        elif version == 1:
            self._db.execute("""
                CREATE TABLE artifacts(
                  artifact_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL, mime_type TEXT NOT NULL,
                  size INTEGER NOT NULL, sha256 TEXT NOT NULL, storage_name TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
                )
            """)
            self._db.execute("UPDATE gateway_schema SET version=?", (SCHEMA_VERSION,))
        if version in {1, 2}:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS gateway_refresh_tokens(
                  token_hash TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                  device_name TEXT, expires_at REAL NOT NULL, scopes_json TEXT NOT NULL,
                  FOREIGN KEY(device_id) REFERENCES trusted_devices(device_id)
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS used_access_jtis(
                  jti TEXT PRIMARY KEY, used_at REAL NOT NULL
                )
            """)
            self._db.execute("UPDATE gateway_schema SET version=?", (SCHEMA_VERSION,))
        if version in {1, 2, 3}:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS gateway_approvals(
                  approval_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                  session_id TEXT, run_id TEXT, tool_call_id TEXT, tool_name TEXT NOT NULL,
                  status TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL,
                  expires_at REAL NOT NULL, decided_at REAL, decision_device_id TEXT
                )
            """)
            self._db.execute("UPDATE gateway_schema SET version=?", (SCHEMA_VERSION,))
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS gateway_runtime_status(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              instance_id TEXT NOT NULL, state TEXT NOT NULL, heartbeat_at REAL NOT NULL,
              bind_host TEXT NOT NULL, tls_active INTEGER NOT NULL,
              connected_devices INTEGER NOT NULL, error_code TEXT
            )
        """)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def trust_device(
        self, *, device_id: str, device_name: str, public_key: str,
        key_fingerprint: str, workspace_id: str, created_at: float,
    ) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO trusted_devices VALUES (?,?,?,?,?,1,?,NULL)",
                (device_id, device_name, public_key, key_fingerprint, workspace_id, created_at),
            )

    def device(self, device_id: str) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM trusted_devices WHERE device_id=?", (device_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def list_devices(self, *, workspace_id: str) -> list[Mapping[str, object]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM trusted_devices WHERE workspace_id=? ORDER BY created_at",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_device(self, device_id: str, *, revoked_at: float) -> bool:
        with self.transaction():
            changed = self._db.execute(
                "UPDATE trusted_devices SET active=0,revoked_at=? WHERE device_id=? AND active=1",
                (revoked_at, device_id),
            ).rowcount
            self._db.execute(
                "UPDATE device_sessions SET disconnected_at=? WHERE device_id=? AND disconnected_at IS NULL",
                (revoked_at, device_id),
            )
            self._db.execute(
                "DELETE FROM gateway_refresh_tokens WHERE device_id=?", (device_id,)
            )
        return changed > 0

    def open_connection(self, connection_id: str, device_id: str, now: float) -> None:
        with self.transaction():
            row = self._db.execute(
                "SELECT active FROM trusted_devices WHERE device_id=?", (device_id,)
            ).fetchone()
            if row is None or not bool(row[0]):
                raise GatewayStoreError("device is not trusted")
            self._db.execute(
                "INSERT INTO device_sessions VALUES (?,?,?,NULL)",
                (connection_id, device_id, now),
            )

    def close_connection(self, connection_id: str, now: float) -> None:
        with self.transaction():
            self._db.execute(
                "UPDATE device_sessions SET disconnected_at=? WHERE connection_id=? AND disconnected_at IS NULL",
                (now, connection_id),
            )

    def append_event(
        self, *, workspace_id: str, session_id: str | None,
        envelope_json: str, created_at: float,
    ) -> int:
        with self.transaction():
            cursor = self._db.execute(
                "INSERT INTO gateway_events(workspace_id,session_id,envelope_json,created_at) VALUES (?,?,?,?)",
                (workspace_id, session_id, envelope_json, created_at),
            )
            sequence = int(cursor.lastrowid)
            cutoff = self._db.execute(
                """SELECT sequence FROM gateway_events WHERE workspace_id=?
                ORDER BY sequence DESC LIMIT 1 OFFSET ?""",
                (workspace_id, self.event_retention),
            ).fetchone()
            if cutoff is not None:
                self._db.execute(
                    "DELETE FROM gateway_events WHERE workspace_id=? AND sequence<=?",
                    (workspace_id, int(cutoff[0])),
                )
            return sequence

    def events_after(
        self, *, workspace_id: str, sequence: int, limit: int,
    ) -> list[tuple[int, str]]:
        if limit <= 0 or limit > 1000:
            raise ValueError("replay limit must be between 1 and 1000")
        with self._lock:
            newest = self._db.execute(
                "SELECT MAX(sequence) FROM gateway_events WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()[0]
            if sequence > int(newest or 0):
                raise GatewayStoreError("replay cursor is ahead of available history")
            oldest = self._db.execute(
                "SELECT MIN(sequence) FROM gateway_events WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()[0]
            if sequence > 0 and oldest is not None and sequence < int(oldest) - 1:
                raise GatewayStoreError("replay cursor is outside retained history")
            rows = self._db.execute(
                "SELECT sequence,envelope_json FROM gateway_events WHERE workspace_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (workspace_id, sequence, limit),
            ).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]

    def set_cursor(self, device_id: str, stream: str, sequence: int, now: float) -> None:
        with self.transaction():
            current = self._db.execute(
                "SELECT sequence FROM replay_cursors WHERE device_id=? AND stream=?",
                (device_id, stream),
            ).fetchone()
            if current is not None and int(current[0]) > sequence:
                raise GatewayStoreError("cursor cannot move backwards")
            self._db.execute(
                """INSERT INTO replay_cursors VALUES (?,?,?,?)
                ON CONFLICT(device_id,stream) DO UPDATE SET sequence=excluded.sequence,updated_at=excluded.updated_at""",
                (device_id, stream, sequence, now),
            )

    def cursor(self, device_id: str, stream: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT sequence FROM replay_cursors WHERE device_id=? AND stream=?",
                (device_id, stream),
            ).fetchone()
        return 0 if row is None else int(row[0])

    def put_operation(
        self, *, operation_id: str, kind: str, device_id: str,
        workspace_id: str, session_id: str | None, status: str,
        payload: Mapping[str, object], now: float,
    ) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO gateway_operations VALUES (?,?,?,?,?,?,?,?,?)",
                (operation_id, kind, device_id, workspace_id, session_id, status,
                 _json(payload), now, now),
            )

    def update_operation(self, operation_id: str, status: str, now: float) -> bool:
        if status not in {"completed", "failed", "cancelled", "denied", "interrupted"}:
            raise ValueError("invalid terminal operation status")
        with self.transaction():
            changed = self._db.execute(
                """UPDATE gateway_operations SET status=?,updated_at=?
                WHERE operation_id=? AND status IN ('pending','running')""",
                (status, now, operation_id),
            ).rowcount
        return changed > 0

    def operation(
        self, operation_id: str, *, workspace_id: str
    ) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM gateway_operations WHERE operation_id=? AND workspace_id=?",
                (operation_id, workspace_id),
            ).fetchone()
        if row is None:
            return None
        return {**dict(row), "payload": json.loads(str(row["payload_json"]))}

    def operations(
        self, *, workspace_id: str, kind: str | None = None,
    ) -> list[Mapping[str, object]]:
        sql = "SELECT * FROM gateway_operations WHERE workspace_id=?"
        values: list[object] = [workspace_id]
        if kind is not None:
            sql += " AND kind=?"
            values.append(kind)
        sql += " ORDER BY created_at,operation_id"
        with self._lock:
            rows = self._db.execute(sql, values).fetchall()
        return [
            {**dict(row), "payload": json.loads(str(row["payload_json"]))}
            for row in rows
        ]

    def recover_uncertain(self, now: float) -> int:
        with self.transaction():
            changed = self._db.execute(
                "UPDATE gateway_operations SET status='interrupted',updated_at=? WHERE status IN ('pending','running')",
                (now,),
            ).rowcount
            self._db.execute(
                "UPDATE request_results SET status='interrupted' WHERE status='pending'"
            )
            self._db.execute(
                "UPDATE device_sessions SET disconnected_at=? WHERE disconnected_at IS NULL",
                (now,),
            )
            self._db.execute(
                "UPDATE gateway_approvals SET status='interrupted',decided_at=? WHERE status='pending'",
                (now,),
            )
        return changed

    def put_artifact(
        self, *, artifact_id: str, device_id: str, workspace_id: str,
        mime_type: str, size: int, sha256: str, storage_name: str, created_at: float,
    ) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
                (artifact_id, device_id, workspace_id, mime_type, size, sha256,
                 storage_name, created_at),
            )

    def artifact(self, artifact_id: str) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def put_refresh_token(
        self, token_hash: str, *, device_id: str, device_name: str | None,
        expires_at: float, scopes: list[str],
    ) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT OR REPLACE INTO gateway_refresh_tokens VALUES (?,?,?,?,?)",
                (token_hash, device_id, device_name, expires_at, _json(scopes)),
            )

    def pop_refresh_token(self, token_hash: str) -> Mapping[str, object] | None:
        with self.transaction():
            row = self._db.execute(
                "SELECT * FROM gateway_refresh_tokens WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if row is not None:
                self._db.execute(
                    "DELETE FROM gateway_refresh_tokens WHERE token_hash=?", (token_hash,)
                )
        if row is None:
            return None
        return {**dict(row), "scopes": json.loads(str(row["scopes_json"]))}

    def consume_access_jti(self, jti: str, now: float) -> bool:
        try:
            with self.transaction():
                self._db.execute(
                    "DELETE FROM used_access_jtis WHERE used_at<?", (now - 86_400.0,)
                )
                self._db.execute("INSERT INTO used_access_jtis VALUES (?,?)", (jti, now))
            return True
        except sqlite3.IntegrityError:
            return False

    def create_approval(
        self, *, approval_id: str, workspace_id: str, session_id: str | None,
        run_id: str | None, tool_call_id: str | None, tool_name: str,
        reason: str, created_at: float, expires_at: float,
    ) -> None:
        with self.transaction():
            self._db.execute(
                "INSERT INTO gateway_approvals VALUES (?,?,?,?,?,?,'pending',?,?,?,?,NULL)",
                (approval_id, workspace_id, session_id, run_id, tool_call_id,
                 tool_name, reason, created_at, expires_at, None),
            )

    def decide_approval(
        self, *, approval_id: str, workspace_id: str, decision: str,
        device_id: str | None, now: float,
    ) -> bool:
        if decision not in {
            "allowed", "denied", "expired", "cancelled", "interrupted"
        }:
            raise ValueError("invalid approval decision")
        deadline_clause = (
            "AND expires_at>?" if decision in {"allowed", "denied"}
            else ""
        )
        with self.transaction():
            changed = self._db.execute(
                f"""UPDATE gateway_approvals SET status=?,decided_at=?,decision_device_id=?
                WHERE approval_id=? AND workspace_id=? AND status='pending'
                  {deadline_clause}""",
                (decision, now, device_id, approval_id, workspace_id)
                + ((now,) if deadline_clause else ()),
            ).rowcount
        return changed == 1

    def approvals(self, *, workspace_id: str) -> list[Mapping[str, object]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM gateway_approvals WHERE workspace_id=? ORDER BY created_at,approval_id",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def approval(self, approval_id: str) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM gateway_approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def update_runtime_status(
        self, *, instance_id: str, state: str, heartbeat_at: float,
        bind_host: str, tls_active: bool, error_code: str | None = None,
    ) -> None:
        if state not in {"starting", "running", "degraded", "stopped", "error"}:
            raise ValueError("invalid Gateway runtime state")
        with self.transaction():
            connected = int(self._db.execute(
                "SELECT COUNT(*) FROM device_sessions WHERE disconnected_at IS NULL"
            ).fetchone()[0])
            self._db.execute(
                """INSERT OR REPLACE INTO gateway_runtime_status
                VALUES (1,?,?,?,?,?,?,?)""",
                (instance_id, state, heartbeat_at, bind_host, int(tls_active),
                 connected, error_code),
            )

    def runtime_status(self) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM gateway_runtime_status WHERE singleton=1"
            ).fetchone()
        return None if row is None else dict(row)

    def cached_response(
        self, *, device_id: str, workspace_id: str, request_id: str,
    ) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT response_json,status FROM request_results WHERE device_id=? AND workspace_id=? AND request_id=?",
                (device_id, workspace_id, request_id),
            ).fetchone()
        if row is None:
            return None
        if str(row[1]) != "completed":
            raise GatewayStoreError("request outcome is uncertain; replay denied")
        return json.loads(str(row[0]))

    def reserve_request(
        self, *, device_id: str, workspace_id: str, request_id: str, now: float,
    ) -> bool:
        with self.transaction():
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO request_results VALUES (?,?,?,?,?,?)",
                (device_id, workspace_id, request_id, None, "pending", now),
            )
        return cursor.rowcount > 0

    def cache_response(
        self, *, device_id: str, workspace_id: str, request_id: str,
        response: Mapping[str, object], now: float,
    ) -> bool:
        with self.transaction():
            cursor = self._db.execute(
                """UPDATE request_results SET response_json=?,status='completed'
                WHERE device_id=? AND workspace_id=? AND request_id=? AND status='pending'""",
                (_json(response), device_id, workspace_id, request_id),
            )
        return cursor.rowcount > 0

    def put_artifact_grant(self, values: tuple[object, ...]) -> None:
        with self.transaction():
            self._db.execute("INSERT INTO artifact_grants VALUES (?,?,?,?,?,?,?,?,?,?)", values)

    def artifact_grant(self, grant_id: str) -> Mapping[str, object] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM artifact_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def consume_artifact_grant(self, grant_id: str) -> bool:
        with self.transaction():
            changed = self._db.execute(
                "UPDATE artifact_grants SET used=1 WHERE grant_id=? AND used=0",
                (grant_id,),
            ).rowcount
        return changed > 0


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["GatewayStore", "GatewayStoreError", "SCHEMA_VERSION"]
