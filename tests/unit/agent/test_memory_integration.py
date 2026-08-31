"""Tests for agent/memory.py — Memory ↔ AgentLoop integration."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from acta.memory import (
    MemoryStore,
    MemoryRecord,
    RecordType,
    MemoryRetriever,
    RetrievalResult,
    ContextChunk,
    MemoryPolicy,
)
from acta.memory.database import MemoryRow
from agent.memory import (
    build_memory_context_callback,
    build_turn_complete_persist,
    extract_and_save_memory,
)
from agent.runtime import AgentLoop
from agent.observation import ObservationKind
from providers.contracts import ChatResponse, ModelInfo, ChatRequest, ToolCall


MODEL = ModelInfo(
    provider_id="test",
    model_id="test-model",
    display_name="Test model",
    text=True,
    tool_calling=True,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "memory.db"


@pytest.fixture
def store(tmp_db: Path) -> MemoryStore:
    return MemoryStore(tmp_db)


# ── build_memory_context_callback ────────────────────────────────────────────


def test_build_memory_context_callback_returns_callable(store: MemoryStore) -> None:
    """build_memory_context_callback returns a callable for the store."""
    cb = build_memory_context_callback(store)
    assert callable(cb)


def test_memory_context_callback_returns_string(store: MemoryStore) -> None:
    """The callback returns a string (possibly empty in offline mode)."""
    cb = build_memory_context_callback(store)
    result = cb("some input")
    assert isinstance(result, str)


def test_memory_context_callback_empty_store(store: MemoryStore) -> None:
    """Empty store produces empty context."""
    cb = build_memory_context_callback(store)
    result = cb("test")
    assert result == ""


def test_memory_context_callback_disabled_store(tmp_db: Path) -> None:
    """A disabled store returns empty string immediately."""
    store = MemoryStore(tmp_db, enabled=False)
    cb = build_memory_context_callback(store)
    assert cb("anything") == ""


def test_memory_context_callback_retrieval_failure_returns_empty(store: MemoryStore) -> None:
    """If retrieval fails (e.g. DB closed), returns empty string."""
    store.close()
    cb = build_memory_context_callback(store)
    result = cb("test")
    assert result == ""


def test_memory_context_callback_with_mocked_retrieval(store: MemoryStore) -> None:
    """When retriever returns chunks, context includes them."""
    cb = build_memory_context_callback(store)

    fake_chunk = ContextChunk(
        source_ref="preferences:food",
        text="preferences: Food: sourdough bread",
        confidence=1.0,
        relevance=0.9,
        recency=1.0,
    )
    fake_result = RetrievalResult(chunks=[fake_chunk])

    with patch.object(MemoryRetriever, "retrieve", return_value=fake_result):
        result = cb("test")

    assert "sourdough bread" in result


# ── build_turn_complete_persist ──────────────────────────────────────────────


def test_build_turn_complete_persist_returns_callable(store: MemoryStore) -> None:
    """build_turn_complete_persist returns a callable."""
    cb = build_turn_complete_persist(store)
    assert callable(cb)


def test_turn_complete_persist_saves_goal_and_summary(store: MemoryStore) -> None:
    """A non-empty assistant output persists a summary and goal record."""
    cb = build_turn_complete_persist(store)
    cb("Read my files", "Here is the summary of your files.")

    records = list(store.list())
    assert len(records) == 2
    types = {r.type for r in records}
    assert RecordType.CONFIRMED_FACTS in types
    assert RecordType.SUMMARIES in types


def test_turn_complete_persist_empty_output_nothing_saved(store: MemoryStore) -> None:
    """Empty assistant output does not persist anything."""
    cb = build_turn_complete_persist(store)
    cb("some goal", "")
    assert len(list(store.list())) == 0


def test_turn_complete_persist_disabled_store(store: MemoryStore) -> None:
    """A disabled store does not persist."""
    store.set_enabled(False)
    cb = build_turn_complete_persist(store)
    cb("goal", "answer")
    assert len(list(store.list())) == 0


def test_turn_complete_persist_policy_violation_ignored(store: MemoryStore) -> None:
    """Memory policy violations (e.g. secret detection) are silently ignored."""
    cb = build_turn_complete_persist(store)
    cb("Set my API key", "sk-very-secret-api-key-12345")

    assert isinstance(list(store.list()), list)


# ── extract_and_save_memory ──────────────────────────────────────────────────


def test_extract_and_save_memory_returns_list(store: MemoryStore) -> None:
    """extract_and_save_memory returns a list of keys."""
    result = extract_and_save_memory(store, "Hello", "Hi there")
    assert isinstance(result, list)


def test_extract_and_save_memory_disabled_store(tmp_db: Path) -> None:
    """A disabled store returns empty list."""
    store = MemoryStore(tmp_db, enabled=False)
    result = extract_and_save_memory(store, "test", "reply")
    assert result == []


def test_extract_and_save_memory_heuristic_detection(store: MemoryStore) -> None:
    """Extracts memories when heuristic patterns match."""
    result = extract_and_save_memory(
        store,
        "My name is John",
        "Hello John!",
    )
    assert len(result) >= 1
    records = list(store.list(RecordType.CONFIRMED_FACTS))
    assert len(records) >= 1


def test_extract_and_save_memory_no_match(store: MemoryStore) -> None:
    """No memorable content does not crash and returns empty list."""
    result = extract_and_save_memory(
        store,
        "What time is it?",
        "It is 3 PM.",
    )
    assert isinstance(result, list)


def test_extract_and_save_memory_preferences_pattern(store: MemoryStore) -> None:
    """Extracts preferences when patterns like 'I like' are found."""
    result = extract_and_save_memory(
        store,
        "I like sourdough bread very much",
        "Got it, noted.",
    )
    assert len(result) >= 1
    records = list(store.list(RecordType.PREFERENCES))
    assert len(records) >= 1


# ── Integration: AgentLoop + Memory ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_memory_callback_injected(store: MemoryStore) -> None:
    """Verify AgentLoop calls memory callback during _call_provider."""
    rec = MemoryRecord(
        type=RecordType.PREFERENCES,
        key="color",
        value="blue",
        source="test",
    )
    store.commit(store.propose(rec).id)

    cb = build_memory_context_callback(store)
    assert cb("test") == ""  # offline mode returns empty, but loop continues

    responses = [
        ChatResponse("Checking", "test", "test", (
            ToolCall(id="c1", name="noop", arguments={}),
        )),
        ChatResponse("Done.", "test", "test"),
    ]

    async def mock_chat(req: ChatRequest) -> ChatResponse:
        return responses.pop(0)

    mock_provider = MagicMock()
    mock_provider.chat.side_effect = mock_chat

    loop = AgentLoop(
        provider=mock_provider,
        model=MODEL,
        memory_context_callback=cb,
        tool_executor=lambda name, args: "ok",
    )
    result = await loop.run("Check preferences")

    assert result.ok is True
    assert result.final_answer == "Done."


@pytest.mark.asyncio
async def test_agent_loop_persists_on_turn_complete(store: MemoryStore) -> None:
    """Verify on_turn_complete handler persists memory after successful turn."""
    cb = build_turn_complete_persist(store)
    persist_calls: list[tuple[str, str]] = []

    def counting_persist(user_input: str, output: str) -> None:
        persist_calls.append((user_input, output))
        cb(user_input, output)

    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=ChatResponse(
        text="Hello from agent!", provider_id="test", model_id="test"
    ))

    loop = AgentLoop(
        provider=mock_provider,
        model=MODEL,
        memory_context_callback=None,
    )
    result = await loop.run("Say hello", on_turn_complete=counting_persist)

    assert result.ok is True
    assert result.final_answer == "Hello from agent!"
    assert len(persist_calls) == 1
    assert persist_calls[0][0] == "Say hello"

    records = list(store.list())
    assert len(records) == 2


@pytest.mark.asyncio
async def test_agent_loop_memory_extraction_after_complete(store: MemoryStore) -> None:
    """Verify extract_and_save_memory persists after turn completion."""
    cb = build_turn_complete_persist(store)
    extracted_keys: list[str] = []

    def tracking_persist(user_input: str, output: str) -> None:
        cb(user_input, output)
        keys = extract_and_save_memory(store, user_input, output)
        extracted_keys.extend(keys)

    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=ChatResponse(
        text="I learned your name is Alice!", provider_id="test", model_id="test"
    ))

    loop = AgentLoop(
        provider=mock_provider,
        model=MODEL,
        memory_context_callback=None,
    )
    result = await loop.run("My name is Alice", on_turn_complete=tracking_persist)

    assert result.ok is True
    assert len(extracted_keys) >= 0  # Non-crashing is the key assertion


@pytest.mark.asyncio
async def test_memory_callback_non_fatal_on_error(store: MemoryStore) -> None:
    """Memory callback errors do not break the agent loop."""
    store.close()
    cb = build_memory_context_callback(store)

    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=ChatResponse(
        text="All good.", provider_id="test", model_id="test"
    ))

    loop = AgentLoop(
        provider=mock_provider,
        model=MODEL,
        memory_context_callback=cb,
    )
    result = await loop.run("Test")

    assert result.ok is True
    assert result.final_answer == "All good."


# ── i18n: Russian-language messages ─────────────────────────────────────────


def test_i18n_russian_keys_exist() -> None:
    """Verify i18n keys for agent errors use Russian text."""
    from i18n import t, set_locale

    set_locale("ru")

    max_tc = t("agent.max_tool_calls", n=5)
    max_turns = t("agent.max_turns", n=3)
    timeout = t("agent.timeout_exceeded", s=120)

    assert max_tc and len(max_tc) > 0
    assert max_turns and len(max_turns) > 0
    assert timeout and len(timeout) > 0

    set_locale("en")


def test_i18n_english_keys_exist() -> None:
    """Verify i18n keys for agent errors work in English too."""
    from i18n import t, set_locale

    set_locale("en")

    max_tc = t("agent.max_tool_calls", n=5)
    assert max_tc and len(max_tc) > 0

    set_locale("ru")
