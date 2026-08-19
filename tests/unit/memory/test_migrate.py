from __future__ import annotations

from pathlib import Path

from mark.memory import MemoryStore, RecordType, migrate_json

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "legacy_memory.json"

ALLOWED = {
    ("confirmed_facts", "name", "Alex"),
    ("confirmed_facts", "city", "Helsinki"),
    ("preferences", "food", "sourdough"),
    ("projects", "mark", "desktop client"),
    ("confirmed_facts", "coworker", "Sam is a teammate"),
    ("preferences", "travel", "visit Kyoto"),
    ("summaries", "meeting", "weekly sync on Mondays"),
}

SECRET_VALUES = {
    "4111111111111111",
    "sk-abcdefghijklmnopqrstuvwxyz012345",
    "not-a-real-password",
    "Bearer tok_live_not_a_real_secret_value",
}


def test_fixture_migrates_allowed_categories_and_skips_secrets(
    store: MemoryStore,
) -> None:
    stats = store.migrate_json(FIXTURE)
    assert stats.migrated == len(ALLOWED)
    assert stats.skipped_secrets == 4
    assert stats.by_legacy_category["identity"] == 2
    assert stats.by_legacy_category["preferences"] == 1
    assert stats.by_legacy_category["projects"] == 1
    assert stats.by_legacy_category["relationships"] == 1
    assert stats.by_legacy_category["wishes"] == 1
    assert stats.by_legacy_category["notes"] == 1
    stored = {(item.type.value, item.key, item.value) for item in store.list()}
    assert stored == ALLOWED
    values = {item.value for item in store.list()}
    assert values.isdisjoint(SECRET_VALUES)
    keys = {item.key for item in store.list()}
    assert "api_key" not in keys
    assert "password" not in keys
    assert "card" not in keys


def test_migrate_json_function_accepts_dict(store: MemoryStore) -> None:
    payload = {
        "identity": {"job": "engineer"},
        "preferences": {},
        "projects": {"garden": {"value": "raise tomatoes"}},
        "relationships": {},
        "wishes": {},
        "notes": {},
    }
    stats = migrate_json(payload, store)
    assert stats.migrated == 2
    by_key = {item.key: item for item in store.list()}
    assert by_key["job"].type is RecordType.CONFIRMED_FACTS
    assert by_key["job"].value == "engineer"
    assert by_key["garden"].type is RecordType.PROJECTS
    assert by_key["garden"].source == "legacy_json:projects"
