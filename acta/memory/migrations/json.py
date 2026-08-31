"""Map legacy long-term JSON categories into SQLite record types."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Iterator, Mapping
from pathlib import Path

from acta.memory.errors import (
    CODE_INVALID_MIGRATION,
    MemoryPolicyError,
    MemoryStoreError,
)
from acta.memory.repository import (
    MemoryRecord,
    MemoryStore,
    MigrationStats,
    RecordType,
)

LEGACY_TYPE_MAP: dict[str, RecordType] = {
    "identity": RecordType.CONFIRMED_FACTS,
    "preferences": RecordType.PREFERENCES,
    "projects": RecordType.PROJECTS,
    "relationships": RecordType.CONFIRMED_FACTS,
    "wishes": RecordType.PREFERENCES,
    "notes": RecordType.SUMMARIES,
}


def migrate_json(
    old: Mapping[str, object] | Path,
    store: MemoryStore,
) -> MigrationStats:
    """Write allowed legacy entries through propose/commit. Skip secrets."""
    payload = _load_mapping(old)
    migrated = 0
    skipped_secrets = 0
    skipped_empty = 0
    by_legacy: dict[str, int] = {name: 0 for name in LEGACY_TYPE_MAP}
    by_type: dict[str, int] = {item.value: 0 for item in RecordType}

    for category, record_type in LEGACY_TYPE_MAP.items():
        raw = payload.get(category, {})
        for key, value in _iter_entries(raw):
            if not key or not value.strip():
                skipped_empty += 1
                continue
            try:
                proposal = store.propose(
                    MemoryRecord(
                        type=record_type,
                        key=key,
                        value=value,
                        source=f"legacy_json:{category}",
                    ),
                    workspace="default",
                    user_id="default",
                )
            except MemoryPolicyError:
                skipped_secrets += 1
                continue
            except MemoryStoreError:
                skipped_empty += 1
                continue
            written = store.commit(proposal.id)
            if written is None:
                continue
            migrated += 1
            by_legacy[category] += 1
            by_type[record_type.value] += 1

    return MigrationStats(
        migrated=migrated,
        skipped_secrets=skipped_secrets,
        skipped_empty=skipped_empty,
        by_legacy_category=by_legacy,
        by_type=by_type,
    )


def _load_mapping(old: Mapping[str, object] | Path) -> dict[str, object]:
    if isinstance(old, Path):
        try:
            payload: object = json.loads(old.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MemoryStoreError(CODE_INVALID_MIGRATION) from exc
    else:
        payload = old
    if not isinstance(payload, dict):
        raise MemoryStoreError(CODE_INVALID_MIGRATION)
    return payload


def _iter_entries(node: object, prefix: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        if "value" in node and _is_entry_dict(node):
            raw = node.get("value")
            if raw is None:
                return
            if prefix:
                yield prefix, _stringify(raw)
            return
        for child_key, child in node.items():
            if not isinstance(child_key, str):
                continue
            path = f"{prefix}.{child_key}" if prefix else child_key
            yield from _iter_entries(child, path)
        return
    if node is None:
        return
    if prefix:
        yield prefix, _stringify(node)


def _is_entry_dict(node: Mapping[object, object]) -> bool:
    extra = set(node) - {"value", "updated", "source"}
    return not extra or all(not isinstance(node[key], dict) for key in extra)


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


__all__ = ["LEGACY_TYPE_MAP", "migrate_json"]
