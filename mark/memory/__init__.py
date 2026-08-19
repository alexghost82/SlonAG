"""SQLite memory store with propose-then-commit writes and secret rejection."""

from mark.memory.embeddings import Embedder, EmbeddingService
from mark.memory.errors import (
    CODE_INVALID_MIGRATION,
    CODE_INVALID_RECORD,
    CODE_NOT_FOUND,
    CODE_OK,
    CODE_SECRET_REJECTED,
    CODE_UNKNOWN_PROPOSAL,
    CODE_UNKNOWN_TYPE,
    ERROR_CODES,
    MemoryPolicyError,
    MemoryStoreError,
    memory_message,
)
from mark.memory.migrations import LEGACY_TYPE_MAP, migrate_json
from mark.memory.policy import MemoryPolicy
from mark.memory.repository import (
    MemoryRecord,
    MemoryStore,
    MigrationStats,
    Proposal,
    RecordType,
)

__all__ = [
    "CODE_INVALID_MIGRATION",
    "CODE_INVALID_RECORD",
    "CODE_NOT_FOUND",
    "CODE_OK",
    "CODE_SECRET_REJECTED",
    "CODE_UNKNOWN_PROPOSAL",
    "CODE_UNKNOWN_TYPE",
    "ERROR_CODES",
    "LEGACY_TYPE_MAP",
    "Embedder",
    "EmbeddingService",
    "MemoryPolicy",
    "MemoryPolicyError",
    "MemoryRecord",
    "MemoryStore",
    "MemoryStoreError",
    "MigrationStats",
    "Proposal",
    "RecordType",
    "memory_message",
    "migrate_json",
]
