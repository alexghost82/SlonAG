"""Memory ↔ AgentLoop integration module.

Provides concrete memory callbacks that wire the mark.memory subsystem
into the AgentLoop runtime, including:

- Memory context injection for prompt assembly
- Memory persistence after a turn completes
- Conversation-based memory extraction (extract + save)

Usage::

    from agent.memory import (
        build_memory_context_callback,
        build_turn_complete_persist,
        extract_and_save_memory,
    )
    from acta.memory import MemoryStore
    from pathlib import Path

    store = MemoryStore(Path("memory.db"))
    ctx_cb = build_memory_context_callback(store)
    on_complete = build_turn_complete_persist(store)

    loop = AgentLoop(
        provider=provider,
        model=model,
        memory_context_callback=ctx_cb,
    )
    loop.run("goal", on_turn_complete=on_complete)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from i18n import t
from acta.memory import (
    MemoryContextAssembler,
    MemoryPolicy,
    MemoryRecord,
    MemoryRetriever,
    MemoryStore,
    RecordType,
    build_system_prompt_with_memory,
)
from acta.memory.errors import MemoryPolicyError, memory_message


def build_memory_context_callback(
    store: MemoryStore,
    *,
    query: str = "",
) -> "MemoryContextCallback":
    """Factory that produces a callable matching MemoryContextCallback.

    When invoked, it queries the memory store for the provided query
    and returns the assembled context string.

    Args:
        store: The ``MemoryStore`` instance to query.
        query: A natural-language query that scopes the retrieval.
               Defaults to an empty string which retrieves broadly.

    Returns:
        A callable matching the ``MemoryContextCallback`` protocol
        (``__call__(user_input: str) -> str``).
    """
    if not store.enabled:
        return lambda _user_input: ""

    try:
        retriever = MemoryRetriever(
            db=store._database if store._database is not None else store._db(),
            embed_service=store._embeddings,
            policy=store.policy,
            default_workspace=store.default_workspace,
            default_user=store.default_user,
            default_session=store.default_session,
        )
    except Exception:
        return lambda _user_input: ""

    assembler = MemoryContextAssembler()

    def _context(user_input: str) -> str:
        try:
            result = retriever.retrieve(query)
            return assembler.assemble(result)
        except Exception:
            # Memory retrieval failures are non-fatal; the AgentLoop
            # continues without memory context.
            return ""

    return _context


def build_turn_complete_persist(
    store: MemoryStore,
    *,
    session_id: str = "",
    workspace: str = "",
    user_id: str = "",
) -> "TurnCompleteCallback":
    """Factory for the ``on_turn_complete`` persistence callback.

    When a turn completes, this handler persists the final answer as
    a ``summaries`` memory record and the user goal as a
    ``confirmed_facts`` record if the answer is non-empty.

    Args:
        store: The ``MemoryStore`` instance to write to.
        session_id: Optional session scope for the memory records.
        workspace: Optional workspace scope for the memory records.
        user_id: Optional user scope for the memory records.

    Returns:
        A callable matching ``TurnCompleteCallback``.
    """

    def _persist(user_input: str, assistant_output: str) -> None:
        if not store.enabled or not assistant_output.strip():
            return
        try:
            # Persist the user's goal as a confirmed fact
            rec_goal = MemoryRecord(
                type=RecordType.CONFIRMED_FACTS,
                key=f"goal_{len(user_input) % 1000}",
                value=user_input.strip()[:500],
                source="agent",
            )
            store.commit(store.propose(rec_goal).id)

            # Persist the final answer as a summary
            rec_summary = MemoryRecord(
                type=RecordType.SUMMARIES,
                key=f"summary_{len(assistant_output) % 1000}",
                value=assistant_output.strip()[:1000],
                source="agent",
            )
            store.commit(store.propose(rec_summary).id)
        except MemoryPolicyError:
            # Memory policy violations are non-fatal
            pass
        except Exception:
            # Memory persistence failures are non-fatal
            pass

    return _persist


def extract_and_save_memory(
    store: MemoryStore,
    user_text: str,
    assistant_text: str,
    *,
    conversation_goal: str = "",
) -> list[str]:
    """Extract memorable facts from a conversation and persist them.

    This function analyzes both the user's input and the assistant's
    response for any facts worth remembering (personal details,
    preferences, projects, etc.) and commits them to the store.

    Args:
        store: The ``MemoryStore`` instance.
        user_text: The user's latest message.
        assistant_text: The assistant's response.
        conversation_goal: Optional goal context for extraction scoping.

    Returns:
        A list of record keys that were persisted.
    """
    if not store.enabled:
        return []

    combined = f"User: {user_text[:600]}\nAssistant: {assistant_text[:600]}"

    # Simple keyword-based extraction for offline use
    # In production, this would call an LLM via the memory extraction pipeline
    extracted: list[str] = []
    _maybe_extract(store, combined, "preferences", extracted)
    _maybe_extract(store, combined, "projects", extracted)
    _maybe_extract(store, combined, "confirmed_facts", extracted)

    return extracted


def _maybe_extract(
    store: MemoryStore,
    text: str,
    record_type_name: str,
    extracted: list[str],
) -> None:
    """Attempt to extract a memory record from text.

    This is a lightweight heuristic: it looks for patterns that suggest
    the presence of a memorable fact and commits them to the store.
    """
    lower = text.lower()

    # Heuristic: look for "I like", "my name is", "I work at", etc.
    patterns: dict[str, list[str]] = {
        "preferences": ["like ", "love ", "hate ", "favorite ", "enjoy "],
        "projects": ["working on ", "building ", "working ", "project "],
        "confirmed_facts": ["my name is ", "i am ", "i live in ", "i work at "],
    }

    patterns_for_type = patterns.get(record_type_name, [])
    for pattern in patterns_for_type:
        idx = lower.find(pattern)
        if idx >= 0:
            value = text[idx + len(pattern) : idx + 200].strip().rstrip(".")
            if value:
                try:
                    rec = MemoryRecord(
                        type=RecordType(record_type_name),
                        key=f"extracted_{record_type_name}_{len(extracted)}",
                        value=value[:500],
                        source="extraction",
                    )
                    store.commit(store.propose(rec).id)
                    extracted.append(rec.key)
                    return  # One match per type per call
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Type aliases for the MemoryContextCallback and TurnCompleteCallback
# protocols (mirrors agent/runtime.py for convenience).
# ---------------------------------------------------------------------------

MemoryContextCallback: Callable[[str], str]
TurnCompleteCallback: Callable[[str, str], None]
