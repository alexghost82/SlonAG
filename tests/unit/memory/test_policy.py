from __future__ import annotations

import pytest

from acta.memory import (
    CODE_SECRET_REJECTED,
    MemoryPolicy,
    MemoryPolicyError,
    MemoryRecord,
    MemoryStore,
    RecordType,
)

KEY_LIKE = "sk-abcdefghijklmnopqrstuvwxyz012345"
GEMINI_LIKE = "AIzaSyDummyValueThatLooksLikeAKey99"
BEARER_LIKE = "Bearer tok_live_not_a_real_secret_value"
TEST_PAN = "4111111111111111"


def _record(key: str, value: str) -> MemoryRecord:
    return MemoryRecord(
        type=RecordType.PREFERENCES,
        key=key,
        value=value,
        source="user",
    )


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("password", "not-a-real-password"),
        ("api_key", "dummy"),
        ("openrouter_token", "dummy"),
        ("note", KEY_LIKE),
        ("note", GEMINI_LIKE),
        ("note", BEARER_LIKE),
        ("note", TEST_PAN),
        ("note", "4111 1111 1111 1111"),
        ("note", "password=hunter2-not-real"),
    ),
)
def test_secrets_rejected_on_propose(
    store: MemoryStore, key: str, value: str
) -> None:
    with pytest.raises(MemoryPolicyError) as exc_info:
        store.propose(_record(key, value))
    assert exc_info.value.code == CODE_SECRET_REJECTED
    message = str(exc_info.value)
    assert value not in message
    assert store.list() == []


def test_ordinary_preference_is_allowed(store: MemoryStore) -> None:
    proposal = store.propose(_record("food", "sourdough"))
    record = store.commit(proposal.id)
    assert record is not None
    assert record.value == "sourdough"


def test_extra_categories_are_configurable(db_path) -> None:
    policy = MemoryPolicy(extra_categories=("health", "ssn"))
    store = MemoryStore(db_path, policy=policy)
    with pytest.raises(MemoryPolicyError) as exc_info:
        store.propose(_record("health_note", "asthma"))
    assert exc_info.value.code == CODE_SECRET_REJECTED
    assert "asthma" not in str(exc_info.value)
    allowed = store.propose(_record("food", "sourdough"))
    assert store.commit(allowed.id) is not None
    store.close()


def test_update_rejects_secret_and_keeps_original(store: MemoryStore) -> None:
    proposal = store.propose(_record("food", "sourdough"))
    record = store.commit(proposal.id)
    assert record is not None
    with pytest.raises(MemoryPolicyError):
        store.update(record.id, value=KEY_LIKE)
    assert store.get(record.id) is not None
    got = store.get(record.id)
    assert got is not None
    assert got.value == "sourdough"
