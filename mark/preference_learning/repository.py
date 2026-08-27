"""SQLite-backed persistence for the preference learning system."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from mark.preference_learning.types import (
    LearnedItem,
    PreferenceVersion,
    RetrievalContext,
    _now,
)


class PreferenceRepository:
    """File-based persistence using SQLite with a JSON columns for full history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).parent / "preference_learning.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        import sqlite3

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    type TEXT NOT NULL DEFAULT 'explicit',
                    action TEXT NOT NULL DEFAULT 'apply',
                    priority TEXT NOT NULL DEFAULT 'medium',
                    category TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    decay_policy TEXT NOT NULL DEFAULT 'none',
                    max_reinforcements INTEGER NOT NULL DEFAULT 50,
                    reinforcement_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_use_at TEXT,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    contradicted INTEGER NOT NULL DEFAULT 0,
                    corrected INTEGER NOT NULL DEFAULT 0,
                    correction_source TEXT NOT NULL DEFAULT 'manual_entry',
                    correction_reason TEXT NOT NULL DEFAULT '',
                    deleted INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pref_key ON preferences(key)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pref_category ON preferences(category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pref_type ON preferences(type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pref_deleted ON preferences(deleted)
            """)
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------
    # Read / Write
    # ------------------------------------------------------------------

    def save(self, item: LearnedItem) -> str:
        """Upsert a preference item. Returns the item id."""
        import sqlite3

        active = item.active
        if active is None:
            raise ValueError("Saved LearnedItem has no version")

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                tags_json = json.dumps(active.tags, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO preferences
                        (id, key, value, version, type, action, priority,
                         category, description, confidence, decay_policy,
                         max_reinforcements, reinforcement_count,
                         created_at, updated_at, last_use_at, usage_count,
                         contradicted, corrected, correction_source,
                         correction_reason, deleted, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        key=excluded.key, value=excluded.value,
                        version=excluded.version, type=excluded.type,
                        action=excluded.action, priority=excluded.priority,
                        category=excluded.category, description=excluded.description,
                        confidence=excluded.confidence, decay_policy=excluded.decay_policy,
                        max_reinforcements=excluded.max_reinforcements,
                        reinforcement_count=excluded.reinforcement_count,
                        created_at=excluded.created_at, updated_at=excluded.updated_at,
                        last_use_at=excluded.last_use_at, usage_count=excluded.usage_count,
                        contradicted=excluded.contradicted, corrected=excluded.corrected,
                        correction_source=excluded.correction_source,
                        correction_reason=excluded.correction_reason,
                        deleted=excluded.deleted, tags=excluded.tags
                    """,
                    (
                        item.id,
                        active.key,
                        active.value,
                        active.version,
                        active.type.value,
                        active.action.value,
                        active.priority.value,
                        active.category,
                        active.description,
                        active.confidence,
                        active.decay_policy.value,
                        active.max_reinforcements,
                        active.reinforcement_count,
                        active.created_at,
                        active.updated_at,
                        active.last_use_at,
                        active.usage_count,
                        1 if active.contradicted else 0,
                        1 if active.corrected else 0,
                        active.correction_source.value,
                        active.correction_reason,
                        1 if active.deleted else 0,
                        tags_json,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return item.id

    def load(self, item_id: str) -> LearnedItem | None:
        import sqlite3

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                row = conn.execute(
                    "SELECT * FROM preferences WHERE id = ?", (item_id,)
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return None
        return self._row_to_item(row)

    def list_items(
        self,
        *,
        include_deleted: bool = False,
        category: str | None = None,
        pref_type: str | None = None,
        min_confidence: float = 0.0,
        tag_filter: str | None = None,
    ) -> list[LearnedItem]:
        import sqlite3

        conditions: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            conditions.append("deleted = 0")
        if category:
            conditions.append("category = ?")
            params.append(category)
        if pref_type:
            conditions.append("type = ?")
            params.append(pref_type)
        if min_confidence > 0:
            conditions.append("confidence >= ?")
            params.append(min_confidence)
        if tag_filter:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag_filter}%")

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                rows = conn.execute(
                    f"SELECT * FROM preferences{where} ORDER BY updated_at DESC",
                    params,
                ).fetchall()
            finally:
                conn.close()

        return [self._row_to_item(row) for row in rows]

    def list_all_with_history(self, include_deleted: bool = False) -> list[LearnedItem]:
        """List all items including their full version history from stored history."""
        items = self.list_items(include_deleted=include_deleted)
        return items

    def delete(self, item_id: str) -> bool:
        """Hard-delete a preference from storage."""
        import sqlite3

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute("DELETE FROM preferences WHERE id = ?", (item_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def count(self, include_deleted: bool = False) -> int:
        import sqlite3

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                if include_deleted:
                    return conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
                return conn.execute(
                    "SELECT COUNT(*) FROM preferences WHERE deleted = 0"
                ).fetchone()[0]
            finally:
                conn.close()

    def clear_all(self) -> int:
        import sqlite3

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.execute("DELETE FROM preferences")
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Search / Retrieve
    # ------------------------------------------------------------------

    def retrieve_matching(
        self, context: RetrievalContext
    ) -> list[tuple[LearnedItem, float]]:
        """Return preferences relevant to the given context, scored by confidence."""
        items = self.list_items(
            category=context.category_filter,
            min_confidence=context.min_confidence,
        )
        scored: list[tuple[LearnedItem, float]] = []
        task_lower = context.current_task.lower()

        for item in items:
            active = item.active
            if active is None or active.deleted:
                continue

            score = self._compute_relevance(item, context, task_lower)
            if score > 0:
                scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:context.max_results]

    def _compute_relevance(
        self, item: LearnedItem, context: RetrievalContext, task_lower: str
    ) -> float:
        active = item.active
        if active is None:
            return 0.0

        score = active.confidence

        # Category match bonus
        if context.category_filter and active.category == context.category_filter:
            score += 0.2

        # Keyword match in value/description against task/tool
        text_fields = f"{active.value} {active.description} {active.key} {active.category}"
        if context.tool_name and context.tool_name.lower() in text_fields.lower():
            score += 0.15
        if task_lower and any(
            word in text_fields.lower() for word in task_lower.split()[:5]
        ):
            score += 0.1

        # Usage bonus — frequently used preferences gain a small score
        if active.usage_count > 0:
            score += min(0.1, active.usage_count * 0.02)

        # Correction penalty
        if active.corrected:
            score *= 0.0

        # Contraction penalty
        if active.contradicted:
            score *= 0.2

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_item(self, row: tuple | list) -> LearnedItem:
        cols = [
            "id", "key", "value", "version", "type", "action", "priority",
            "category", "description", "confidence", "decay_policy",
            "max_reinforcements", "reinforcement_count", "created_at",
            "updated_at", "last_use_at", "usage_count", "contradicted",
            "corrected", "correction_source", "correction_reason", "deleted",
            "tags",
        ]
        d = dict(zip(cols, row))
        d["contradicted"] = bool(d["contradicted"])
        d["corrected"] = bool(d["corrected"])
        d["deleted"] = bool(d["deleted"])
        try:
            tags = json.loads(d.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = []
        active = PreferenceVersion(
            id=d["id"],
            version=d["version"],
            type=PreferenceType(d["type"]),
            action=PreferenceAction(d["action"]),
            priority=PriorityLevel(d["priority"]),
            category=d["category"],
            key=d["key"],
            value=d["value"],
            description=d["description"],
            confidence=d["confidence"],
            decay_policy=ConfidenceDecayPolicy(d["decay_policy"]),
            max_reinforcements=d["max_reinforcements"],
            reinforcement_count=d["reinforcement_count"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            last_use_at=d.get("last_use_at", ""),
            usage_count=d["usage_count"],
            contradicted=d["contradicted"],
            contradiction_evidence=[],  # Not stored in simple model
            correction_source=LearningSource(d.get("correction_source", "manual_entry")),
            correction_reason=d.get("correction_reason", ""),
            deleted=d["deleted"],
            tags=tags,
        )
        return LearnedItem(
            id=d["id"],
            versions=[active],
            created_at=d["created_at"],
        )
