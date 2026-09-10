"""Canonical persistent Job Engine (SQLite WAL).

This is the only crash-safe job queue. ``agent.task_queue.TaskQueue`` remains
an in-RAM adapter for queued text turns and must not grow a second store.

``acta.automation`` owns schedules/triggers. ``acta.proactive`` filters
suggestions. ``acta.workflow_learning`` mines templates. None of those is a
Job Engine — they enqueue work here when they need durable execution.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    RETRYING = "retrying"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class Job:
    job_id: str
    type: str
    payload: dict[str, Any]
    state: JobState
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    attempt: int
    max_attempts: int
    next_retry_at: str | None
    owner: str
    session_id: str
    idempotency_key: str
    checkpoint: dict[str, Any]
    error: str | None
    result_ref: str | None
    cancellation: str | None


class JobEngine:
    """Crash-safe jobs with idempotent enqueue and restart recovery."""

    def __init__(self, db_path: Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _init_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    attempt INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    next_retry_at TEXT,
                    owner TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL,
                    checkpoint TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    result_ref TEXT,
                    cancellation TEXT
                )
                """
            )
            self._connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state)")

    def enqueue(
        self,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        owner: str = "",
        session_id: str = "",
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        key = (idempotency_key or "").strip() or uuid4().hex
        now = _iso(_now()) or ""
        job_id = uuid4().hex
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                return _row_to_job(existing)
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO jobs (
                        job_id, type, payload, state, created_at, updated_at,
                        started_at, finished_at, attempt, max_attempts, next_retry_at,
                        owner, session_id, idempotency_key, checkpoint, error,
                        result_ref, cancellation
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?, NULL, ?, ?, ?, '{}', NULL, NULL, NULL)
                    """,
                    (
                        job_id,
                        type,
                        json.dumps(payload or {}, ensure_ascii=False),
                        JobState.PENDING,
                        now,
                        now,
                        max(1, int(max_attempts)),
                        owner,
                        session_id,
                        key,
                    ),
                )
            return self._get_unlocked(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._get_unlocked(job_id)

    def _get_unlocked(self, job_id: str) -> Job | None:
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return _row_to_job(row) if row is not None else None

    def get_by_idempotency_key(self, key: str) -> Job | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    def claim(self, *, now: datetime | None = None, job_type: str | None = None) -> Job | None:
        """Atomically move one due PENDING/RETRYING job to RUNNING."""
        stamp = now or _now()
        iso = _iso(stamp) or ""
        type_clause = " AND type = ?" if job_type else ""
        params: tuple[object, ...] = (JobState.PENDING, JobState.RETRYING, iso)
        if job_type:
            params = params + (job_type,)
        with self._lock:
            with self._connection:
                row = self._connection.execute(
                    f"""
                    SELECT * FROM jobs
                    WHERE state IN (?, ?)
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                      {type_clause}
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    params,
                ).fetchone()
                if row is None:
                    return None
                job = _row_to_job(row)
                attempt = job.attempt + 1
                self._connection.execute(
                    """
                    UPDATE jobs
                    SET state = ?, attempt = ?, started_at = COALESCE(started_at, ?),
                        updated_at = ?, error = NULL
                    WHERE job_id = ? AND state IN (?, ?)
                    """,
                    (
                        JobState.RUNNING,
                        attempt,
                        iso,
                        iso,
                        job.job_id,
                        JobState.PENDING,
                        JobState.RETRYING,
                    ),
                )
            return self._get_unlocked(job.job_id)

    def claim_job(self, job_id: str, *, now: datetime | None = None) -> Job | None:
        """Atomically move this PENDING/RETRYING job to RUNNING."""
        stamp = now or _now()
        iso = _iso(stamp) or ""
        with self._lock:
            with self._connection:
                row = self._connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE job_id = ? AND state IN (?, ?)
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    """,
                    (job_id, JobState.PENDING, JobState.RETRYING, iso),
                ).fetchone()
                if row is None:
                    return None
                job = _row_to_job(row)
                attempt = job.attempt + 1
                self._connection.execute(
                    """
                    UPDATE jobs
                    SET state = ?, attempt = ?, started_at = COALESCE(started_at, ?),
                        updated_at = ?, error = NULL
                    WHERE job_id = ? AND state IN (?, ?)
                    """,
                    (
                        JobState.RUNNING,
                        attempt,
                        iso,
                        iso,
                        job.job_id,
                        JobState.PENDING,
                        JobState.RETRYING,
                    ),
                )
            return self._get_unlocked(job.job_id)

    def checkpoint(self, job_id: str, data: dict[str, Any]) -> Job:
        return self._update(
            job_id,
            checkpoint=json.dumps(data, ensure_ascii=False),
        )

    def complete(self, job_id: str, *, result_ref: str | None = None) -> Job:
        job = self._require(job_id)
        if job.state in _TERMINAL:
            return job
        now = _iso(_now())
        return self._update(
            job_id,
            state=JobState.COMPLETED,
            finished_at=now,
            result_ref=result_ref,
            error=None,
        )

    def fail(self, job_id: str, error: str, *, retry: bool = True) -> Job:
        job = self._require(job_id)
        if job.state in _TERMINAL:
            return job
        now = _now()
        if retry and job.attempt < job.max_attempts:
            delay = 0.0 if error == "recovered_after_crash" else min(60.0, 2 ** max(0, job.attempt - 1))
            return self._update(
                job_id,
                state=JobState.RETRYING,
                error=error,
                next_retry_at=_iso(now + timedelta(seconds=delay)),
            )
        return self._update(
            job_id,
            state=JobState.FAILED,
            error=error,
            finished_at=_iso(now),
        )

    def cancel(self, job_id: str, *, reason: str = "user") -> Job:
        job = self._require(job_id)
        if job.state in _TERMINAL:
            return job
        return self._update(
            job_id,
            state=JobState.CANCELLED,
            cancellation=reason,
            finished_at=_iso(_now()),
        )

    def pause(self, job_id: str) -> Job:
        job = self._require(job_id)
        if job.state in _TERMINAL:
            return job
        return self._update(job_id, state=JobState.PAUSED)

    def resume(self, job_id: str) -> Job:
        job = self._require(job_id)
        if job.state != JobState.PAUSED:
            return job
        return self._update(job_id, state=JobState.PENDING, next_retry_at=None)

    def recover_running(self) -> list[Job]:
        """After a crash: RUNNING jobs become RETRYING or FAILED. No duplicate complete."""
        recovered: list[Job] = []
        with self._lock:
            rows = list(
                self._connection.execute(
                    "SELECT * FROM jobs WHERE state = ?",
                    (JobState.RUNNING,),
                )
            )
        for row in rows:
            job = _row_to_job(row)
            recovered.append(self.fail(job.job_id, "recovered_after_crash", retry=True))
        return recovered

    def list_by_state(self, state: JobState, *, job_type: str | None = None) -> list[Job]:
        with self._lock:
            if job_type:
                rows = self._connection.execute(
                    "SELECT * FROM jobs WHERE state = ? AND type = ? ORDER BY created_at ASC",
                    (state, job_type),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC",
                    (state,),
                ).fetchall()
        return [_row_to_job(row) for row in rows]

    def _require(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _update(self, job_id: str, **fields: Any) -> Job:
        assignments = ["updated_at = ?"]
        values: list[Any] = [_iso(_now())]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        with self._lock:
            with self._connection:
                self._connection.execute(
                    f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?",
                    values,
                )
            return self._require_unlocked(job_id)

    def _require_unlocked(self, job_id: str) -> Job:
        job = self._get_unlocked(job_id)
        if job is None:
            raise KeyError(job_id)
        return job


def _row_to_job(row: sqlite3.Row) -> Job:
    payload = json.loads(row["payload"] or "{}")
    checkpoint = json.loads(row["checkpoint"] or "{}")
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    return Job(
        job_id=str(row["job_id"]),
        type=str(row["type"]),
        payload=payload,
        state=JobState(row["state"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        next_retry_at=row["next_retry_at"],
        owner=str(row["owner"] or ""),
        session_id=str(row["session_id"] or ""),
        idempotency_key=str(row["idempotency_key"]),
        checkpoint=checkpoint,
        error=row["error"],
        result_ref=row["result_ref"],
        cancellation=row["cancellation"],
    )


__all__ = ["Job", "JobEngine", "JobState"]
