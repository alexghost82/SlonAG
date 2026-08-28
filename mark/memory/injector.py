"""Memory injector for AgentLoop integration.

Provides a clean interface between AgentLoop.run() → _call_provider() chain:
conversation/event → memory candidate → policy → persistence →
embedding/index → retrieval → ranking → bounded context selection →
AgentLoop prompt/context → response.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mark.memory.repository import MemoryStore


@dataclass
class MemoryCandidate:
    """A potential memory fact extracted from conversation.

    Attributes:
        type: memory category (e.g. confirmed_facts, preferences)
        key: identifier
        value: the fact to store
        confidence: 0-1 trust level
    """

    type: str
    key: str
    value: str
    confidence: float = 1.0


class MemoryInjector:
    """Bridge between AgentLoop turns and the MemoryStore.

    - On each turn, injects retrieved memory into the prompt.
    - On turn completion, stores durable facts from the conversation.
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        workspace: str = "default",
        user_id: str = "default",
        session_id: str = "",
        extract_on_turn: bool = True,
        retrieve_on_turn: bool = True,
    ) -> None:
        self._store = store
        self._workspace = workspace
        self._user_id = user_id
        self._session_id = session_id
        self._extract_on_turn = extract_on_turn
        self._retrieve_on_turn = retrieve_on_turn
        self._last_user_input: str = ""

    # ── retrieval: called BEFORE each model call ──────────────────────

    def build_memory_context(self, user_input: str) -> str:
        """Return memory context string for prompt injection.

        Called before the model provider call.
        """
        if not self._retrieve_on_turn or not self._store.enabled:
            return ""
        from mark.memory.retriever import MemoryRetriever
        from mark.memory.context import MemoryContextAssembler

        retriever = MemoryRetriever(
            self._store._db(),
            embed_service=self._store._embeddings,
            default_workspace=self._workspace,
            default_user=self._user_id,
            default_session=self._session_id,
        )
        result = retriever.retrieve(
            user_input,
            workspace=self._workspace,
            user_id=self._user_id,
            session_id=self._session_id,
        )
        assembler = MemoryContextAssembler()
        return assembler.assemble(result)

    # ── persistence: called AFTER each turn ────────────────────────────

    def persist_candidate(
        self, user_input: str, assistant_output: str) -> list[str]:
        """Extract and persist durable facts from the conversation turn.

        Returns a list of keys that were stored.
        """
        if not self._extract_on_turn or not self._store.enabled:
            return []

        # Only extract if the user input changed
        if user_input == self._last_user_input:
            return []
        self._last_user_input = user_input

        # Extraction is handled by the LLM-based extractor in agent_loop.
        return []

    # ── scope management ──────────────────────────────────────────────

    def set_scope(
        self,
        *,
        workspace: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Update scoping parameters."""
        if workspace is not None:
            self._workspace = workspace
        if user_id is not None:
            self._user_id = user_id
        if session_id is not None:
            self._session_id = session_id

    def clear_scope(self) -> dict[str, str]:
        """Return current scope."""
        return {
            "workspace": self._workspace,
            "user_id": self._user_id,
            "session_id": self._session_id,
        }

    def delete_scope(self) -> int:
        """Delete all memory for the current scope. Returns count."""
        return self._store.delete_scope(
            workspace=self._workspace,
            user_id=self._user_id,
            session_id=self._session_id,
        )

    def list_for_scope(
        self,
        *,
        record_type: str | None = None,
    ) -> list:
        """List memory records for the current scope."""
        return self._store.list(
            record_type=record_type,
            workspace=self._workspace,
            user_id=self._user_id,
            session_id=self._session_id,
        )


__all__ = [
    "MemoryCandidate",
    "MemoryInjector",
]
