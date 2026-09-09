"""SQLite memory store with propose-then-commit writes and secret rejection."""

from acta.memory.context import (
    MemoryContextAssembler,
    build_system_prompt_with_memory,
    commit_extracted_facts,
    format_store_for_prompt,
    is_record_active,
)
from acta.memory.embeddings import Embedder, EmbeddingService
from acta.memory.errors import (
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
from acta.memory.migrations import LEGACY_TYPE_MAP, migrate_json
from acta.memory.migrations.schema import SCHEMA_VERSION, apply_schema
from acta.memory.policy import MemoryPolicy
from acta.memory.repository import (
    MemoryProvenance,
    MemoryRecord,
    MemoryScope,
    MemoryStore,
    MigrationStats,
    Proposal,
    RecordType,
    can_promote_to_personal,
)
from acta.memory.retriever import (
    ContextChunk,
    MemoryRetriever,
    RetrievalResult,
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
    "SCHEMA_VERSION",
    "apply_schema",
    "Embedder",
    "EmbeddingService",
    "MemoryPolicy",
    "MemoryPolicyError",
    "MemoryProvenance",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStore",
    "MemoryStoreError",
    "MemoryContextAssembler",
    "MemoryRetriever",
    "MigrationStats",
    "Proposal",
    "RecordType",
    "RetrievalResult",
    "can_promote_to_personal",
    "ContextChunk",
    "build_system_prompt_with_memory",
    "commit_extracted_facts",
    "format_store_for_prompt",
    "is_record_active",
    "memory_message",
    "migrate_json",
]
