"""Propose-then-commit memory store. The model path never opens SQLite."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Proposal:
    """A validated write that is not yet in SQLite."""

    id: str
    type: RecordType
    key: str
    value: str
    source: str


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
    ) -> None:
        self.db_path = Path(db_path)
        self.policy = policy if policy is not None else MemoryPolicy()
        self.privacy_profile = privacy_profile
        self.network_mode = network_mode
        self._enabled = enabled
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

    def propose(self, record: MemoryRecord) -> Proposal:
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
        proposal = Proposal(
            id=uuid4().hex,
            type=record_type,
            key=key,
            value=value,
            source=source,
        )
        self._pending[proposal.id] = proposal
        return proposal

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
        )
        self._db().insert(_to_row(record))
        del self._pending[proposal_id]
        self._embed_record(record)
        return record

    def list(self, record_type: RecordType | str | None = None) -> list[MemoryRecord]:
        filtered = _coerce_type(record_type) if record_type is not None else None
        type_name = filtered.value if filtered is not None else None
        return [_from_row(row) for row in self._db().list(type_name)]

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
        updated = MemoryRecord(
            id=existing.id,
            type=next_type,
            key=next_key,
            value=next_value,
            source=next_source,
            created_at=existing.created_at,
            updated_at=_now(),
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

    def migrate_json(self, old: Mapping[str, object] | Path) -> MigrationStats:
        from mark.memory.migrations.json import migrate_json as _migrate

        return _migrate(old, self)

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


# Imported lazily by migrate_json; defined here so repository stays the type home.
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


def _to_row(record: MemoryRecord) -> MemoryRow:
    return MemoryRow(
        id=record.id,
        type=record.type.value,
        key=record.key,
        value=record.value,
        source=record.source,
        created_at=record.created_at,
        updated_at=record.updated_at,
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
    )


__all__ = [
    "MemoryRecord",
    "MemoryStore",
    "MigrationStats",
    "Proposal",
    "RecordType",
]
