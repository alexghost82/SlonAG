"""Retrieval pipeline: scoping, ranking, dedup, bounded context.

Responsible for:
- workspace / user / session scoped queries
- relevance (cosine similarity), recency, confidence scoring
- deduplication by hash or near-duplicate value
- bounded context assembly with token budget
- correction and deletion of low-confidence / duplicate entries
- fallback to keyword search when embeddings unavailable
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from acta.memory.database import MemoryDatabase, MemoryRow
from acta.memory.embeddings import EmbeddingService
from acta.memory.errors import MemoryStoreError, memory_message
from acta.memory.policy import MemoryPolicy
from acta.memory.repository import MemoryRecord, RecordType


@dataclass
class ContextChunk:
    """One memory chunk ready for prompt injection.

    Attributes:
        source_ref: human-readable label for provenance
        text: the actual text to inject
        confidence: 0-1 signal about trustworthiness
        relevance: 0-1 cosine similarity score
        recency: 0-1 decay factor
    """

    source_ref: str
    text: str
    confidence: float = 1.0
    relevance: float = 0.0
    recency: float = 1.0


@dataclass
class RetrievalResult:
    """Ranked, deduplicated, scoped memory results."""

    chunks: list[ContextChunk] = field(default_factory=list)
    token_budget_remaining: int = 0
    fallback_used: bool = False
    dedup_removed: int = 0
    privacy_filtered: int = 0


class MemoryRetriever:
    """Query-scoped memory retriever with ranking, dedup, token budget."""

    DEFAULT_TOKEN_BUDGET = 600  # chars reserved for memory in prompt

    def __init__(
        self,
        db: MemoryDatabase,
        *,
        embed_service: EmbeddingService,
        policy: MemoryPolicy | None = None,
        default_workspace: str = "",
        default_user: str = "",
        default_session: str = "",
        max_chunks: int = 8,
        token_budget: int | None = None,
        min_relevance: float = 0.15,
    ) -> None:
        self._db = db
        self._embed_service = embed_service
        self._policy = policy or MemoryPolicy()
        self._workspace = default_workspace
        self._user = default_user
        self._session = default_session
        self._max_chunks = max_chunks
        self._token_budget = token_budget or self.DEFAULT_TOKEN_BUDGET
        self._min_relevance = min_relevance

    # ── public API ────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        *,
        record_type: RecordType | str | None = None,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        include_all_scopes: bool = False,
    ) -> RetrievalResult:
        """Return ranked, deduplicated, scoped memory chunks for a query."""
        ws = workspace if workspace is not None else self._workspace
        uid = user_id if user_id is not None else self._user
        sid = session_id if session_id is not None else self._session

        # Step 1: embed query → vector search, fallback to keyword
        vector = self._embed_service.embed(query)
        fallback_used = False
        if vector is None:
            fallback_used = True
            candidates = self._keyword_search(query, record_type=record_type, top_k=self._max_chunks * 2)
        else:
            candidates = self._vector_search(
                vector, record_type=record_type, top_k=self._max_chunks * 2
            )

        # Step 2: apply workspace/user/session scoping
        if not include_all_scopes:
            candidates = [
                r for r in candidates
                if (
                    r.workspace == ws
                    and r.user_id == uid
                    and (sid == "" or r.session_id == sid)
                )
            ]

        # Step 3: rank — combined score
        scored: list[tuple[MemoryRow, float, float, float]] = []
        for row in candidates:
            relevance = row._similarity if hasattr(row, "_similarity") else 0.0
            recency = self._calc_recency(row.updated_at)
            confidence = row.confidence if hasattr(row, "confidence") else 1.0
            combined = relevance * 0.5 + recency * 0.3 + confidence * 0.2
            scored.append((row, relevance, recency, confidence))

        # Filter by min relevance
        scored = [(r, rel, rec, conf) for r, rel, rec, conf in scored if rel >= self._min_relevance]
        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[: self._max_chunks]

        # Step 4: deduplication (hash + near-duplicate)
        deduped: list[tuple[MemoryRow, float, float, float]] = []
        seen_hashes: set[str] = set()
        seen_values: list[str] = []
        dup_count = 0
        for row, rel, rec, conf in scored:
            h = self._make_hash(row.value)
            if h in seen_hashes:
                dup_count += 1
                continue
            # Near-duplicate: value overlap check
            if self._near_duplicate(row.value, seen_values):
                dup_count += 1
                continue
            seen_hashes.add(h)
            seen_values.append(row.value)
            deduped.append((row, rel, rec, conf))

        # Step 5: build chunks with bounded token budget
        chunks: list[ContextChunk] = []
        budget_left = self._token_budget
        for row, rel, rec, conf in deduped:
            text = self._format_chunk(row)
            if len(text) > budget_left:
                break
            chunks.append(ContextChunk(
                source_ref=f"{row.type}:{row.key}",
                text=text,
                confidence=conf,
                relevance=rel,
                recency=rec,
            ))
            budget_left -= len(text)

        # Step 6: privacy filter
        privacy_filtered = 0
        final_chunks: list[ContextChunk] = []
        for chunk in chunks:
            try:
                self._policy.check(
                    chunk.source_ref.split(":")[0] if ":" in chunk.source_ref else "check",
                    chunk.text,
                )
                final_chunks.append(chunk)
            except MemoryStoreError:
                privacy_filtered += 1

        return RetrievalResult(
            chunks=final_chunks,
            token_budget_remaining=budget_left,
            fallback_used=fallback_used,
            dedup_removed=dup_count,
            privacy_filtered=privacy_filtered,
        )

    def retrieve_for_session(
        self,
        user_input: str,
        *,
        record_type: RecordType | str | None = None,
        include_all_scopes: bool = False,
    ) -> RetrievalResult:
        """Convenience: retrieve for the current workspace/user/session."""
        return self.retrieve(
            user_input,
            record_type=record_type,
            include_all_scopes=include_all_scopes,
        )

    # ── correction & deletion ─────────────────────────────────────────

    def correct(
        self,
        record_id: str,
        *,
        value: str,
        key: str | None = None,
    ) -> MemoryRecord | None:
        """Correct a memory record's value (or key). Returns updated record or None."""
        existing = self._db.get(record_id)
        if existing is None:
            return None
        new_value = value.strip()
        new_key = (key or existing.key).strip()
        if not new_key or not new_value:
            return None
        # Re-check policy
        try:
            self._policy.check(new_key, new_value)
        except MemoryStoreError:
            return None
        import json
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        updated = MemoryRow(
            id=existing.id,
            type=existing.type,
            key=new_key,
            value=new_value,
            source=existing.source,
            created_at=existing.created_at,
            updated_at=now,
            dedup_hash=getattr(existing, "dedup_hash", ""),
            workspace=getattr(existing, "workspace", ""),
            user_id=getattr(existing, "user_id", ""),
            session_id=getattr(existing, "session_id", ""),
            confidence=getattr(existing, "confidence", 1.0),
            recency_weight=getattr(existing, "recency_weight", 1.0),
        )
        self._db.update(updated)
        self._db.upsert_embedding(updated.id, self._embed_service.embed(new_value) or [0.0])
        return MemoryRecord(
            id=updated.id, type=RecordType(updated.type), key=updated.key,
            value=updated.value, source=updated.source,
            created_at=updated.created_at, updated_at=updated.updated_at,
        )

    def delete_low_confidence(self, *, threshold: float = 0.3) -> int:
        """Delete records below confidence threshold. Returns count deleted."""
        rows = self._db.list()
        deleted = 0
        for row in rows:
            conf = row.confidence if hasattr(row, "confidence") else 1.0
            if conf < threshold:
                self._db.delete(row.id)
                deleted += 1
        return deleted

    def delete_by_scope(
        self,
        *,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        """Delete all records matching the given scope filter. Returns count."""
        ws = workspace if workspace is not None else self._workspace
        uid = user_id if user_id is not None else self._user
        sid = session_id if session_id is not None else self._session

        rows = self._db.list()
        deleted = 0
        for row in rows:
            if row.workspace != ws:
                continue
            if row.user_id != uid:
                continue
            if sid != "" and row.session_id != sid:
                continue
            self._db.delete(row.id)
            deleted += 1
        return deleted

    # ── internal helpers ───────────────────────────────────────────────

    def _vector_search(
        self,
        vector: list[float],
        *,
        record_type: RecordType | str | None = None,
        top_k: int = 10,
    ) -> list[MemoryRow]:
        type_name = record_type.value if isinstance(record_type, RecordType) else (record_type or "")
        results = self._db.find_similar(vector, top_k=top_k)
        if type_name:
            results = [r for r in results if r.type == type_name]
        return results

    def _keyword_search(
        self,
        query: str,
        *,
        record_type: RecordType | str | None = None,
        top_k: int = 10,
    ) -> list[MemoryRow]:
        q = query.lower()
        rows = self._db.list()
        if record_type:
            t = record_type.value if isinstance(record_type, RecordType) else str(record_type)
            rows = [r for r in rows if r.type == t]
        scored: list[tuple[MemoryRow, int]] = []
        for row in rows:
            score = 0
            if q in row.key.lower():
                score += 3
            if q in row.value.lower():
                score += 1
            for word in q.split():
                if word in row.key.lower():
                    score += 1
                if word in row.value.lower():
                    score += 1
            if score > 0:
                scored.append((row, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scored[:top_k]]

    def _calc_recency(self, iso_date: str) -> float:
        """0-1 decay: 1.0 = today, 0.0 = >30 days old."""
        try:
            dt = datetime.fromisoformat(iso_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
            return max(0.0, 1.0 - days / 30.0)
        except (ValueError, TypeError):
            return 0.5

    def _format_chunk(self, row: MemoryRow) -> str:
        """Format a single memory record into a short text line."""
        type_label = row.type.split(":")[0] if ":" in row.type else row.type
        return f"{type_label}: {row.key.replace('_', ' ').title()}: {row.value}"

    def _make_hash(self, value: str) -> str:
        return hashlib.sha256(value.lower().strip().encode()).hexdigest()

    def _near_duplicate(self, candidate: str, seen: list[str], *, threshold: float = 0.85) -> bool:
        """Quick near-duplicate check using word overlap."""
        c_words = set(candidate.lower().split())
        if not c_words:
            return False
        for s in seen:
            s_words = set(s.lower().split())
            if not s_words:
                continue
            overlap = len(c_words & s_words) / min(len(c_words), len(s_words))
            if overlap >= threshold:
                return True
        return False


__all__ = [
    "ContextChunk",
    "MemoryRetriever",
    "RetrievalResult",
]
