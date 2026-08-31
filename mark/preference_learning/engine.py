"""Core preference learning engine.

Manages the full lifecycle:
  - Ingest:  create / update / delete preferences
  - Reinforce: boost confidence from repeated use
  - Contradict: handle when new evidence conflicts
  - Retrieve: find relevant preferences for a given context
  - Influence: surface preferences so AgentLoop can use them
"""

from __future__ import annotations

import time
import uuid as _uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from mark.preference_learning.types import (
    Evidence,
    LearnedItem,
    LearningSource,
    PreferenceAction,
    PreferenceType,
    PriorityLevel,
    PreferenceVersion,
    RetrievalContext,
    ConfidenceDecayPolicy,
    _now,
)
from mark.preference_learning.repository import PreferenceRepository


@dataclass
class PreferenceMatch:
    """A preference that matched a retrieval context, with its evidence."""
    item: LearnedItem
    version: PreferenceVersion
    score: float
    evidence: Evidence


@dataclass
class LearningDecision:
    """What the engine decided to do with an observed interaction."""
    action: str                    # "created", "updated", "reinforced", "contradicted", "ignored"
    item_id: str = ""
    reason: str = ""
    old_confidence: float = 0.0
    new_confidence: float = 0.0


class PreferenceEngine:
    """Main API for preference learning and retrieval."""

    DECAY_RATE_LINEAR = 0.05          # 5% per day
    DECAY_FACTOR_EXPONENTIAL = 0.95   # 5% per week

    def __init__(self, db_path: Path, *, max_items: int = 1000) -> None:
        self.repo = PreferenceRepository(db_path)
        self._decay_cache: dict[str, float] = {}
        self.max_items = max_items

    # ===================================================================
    # Ingest — create, update, correct, delete
    # ===================================================================

    def add_preference(
        self,
        *,
        key: str,
        value: str,
        description: str = "",
        pref_type: PreferenceType | str = PreferenceType.EXPLICIT,
        action: PreferenceAction | str = PreferenceAction.APPLY,
        priority: PriorityLevel | str = PriorityLevel.MEDIUM,
        source: LearningSource = LearningSource.USER_STATED,
        evidence: Evidence | None = None,
        category: str = "",
        tags: list[str] | None = None,
    ) -> LearnedItem:
        # Accept str and convert to enum
        if isinstance(pref_type, str):
            pref_type = PreferenceType(pref_type)
        if isinstance(action, str):
            action = PreferenceAction(action)
        if isinstance(priority, str):
            priority = PriorityLevel(priority)
        """Save a new or updated preference. Returns the item."""
        item_id = self._find_existing(key)
        now = _now()

        if item_id is not None:
            # Update existing item
            item = self.repo.load(item_id)
            if item is None:
                raise KeyError(f"Preference item {item_id} vanished")
            active = item.active
            assert active is not None
            new_version = PreferenceVersion(
                id=item_id,
                version=active.version + 1,
                type=pref_type,
                action=action,
                priority=priority,
                category=category or active.category,
                key=key,
                value=value,
                description=description or active.description,
                confidence=active.confidence,  # Keep existing
                decay_policy=active.decay_policy,
                max_reinforcements=active.max_reinforcements,
                reinforcement_count=active.reinforcement_count,
                created_at=active.created_at,
                updated_at=now,
                last_use_at=active.last_use_at,
                usage_count=active.usage_count,
                contradicted=active.contradicted,
                contradiction_evidence=list(active.contradiction_evidence),
                corrected=active.corrected,
                correction_source=active.correction_source,
                correction_reason=active.correction_reason,
                deleted=active.deleted,
                tags=active.tags if active.tags else (tags or []),
            )
            item.versions.append(new_version)
        else:
            # New preference
            confidence = 1.0 if pref_type == PreferenceType.EXPLICIT else 0.5
            decay = ConfidenceDecayPolicy.NONE if pref_type == PreferenceType.EXPLICIT else ConfidenceDecayPolicy.LINEAR
            item = LearnedItem(
                id=uuid4_hex(),
                versions=[
                    PreferenceVersion(
                        id=uuid4_hex(),
                        version=1,
                        type=pref_type,
                        action=action,
                        priority=priority,
                        category=category,
                        key=key,
                        value=value,
                        description=description,
                        confidence=confidence,
                        decay_policy=decay,
                        created_at=now,
                        updated_at=now,
                        tags=tags or [],
                    )
                ],
                created_at=now,
            )

        self.repo.save(item)
        self._enforce_bounds()
        return item

    def correct_preference(
        self,
        key: str,
        new_value: str,
        *,
        reason: str = "",
        source: LearningSource = LearningSource.CORRECTION_RECEIVED,
    ) -> LearnedItem:
        """Record a correction: old behavior should no longer be used."""
        item_id = self._find_existing(key)
        if item_id is None:
            raise KeyError(f"No preference found to correct: {key}")

        item = self.repo.load(item_id)
        if item is None:
            raise KeyError(f"Preference item {item_id} vanished")
        active = item.active
        assert active is not None

        now = _now()
        # Mark old version as deleted (the new version is the active correction)
        active.deleted = True
        new_version = PreferenceVersion(
            id=item_id,
            version=active.version + 1,
            type=PreferenceType.CORRECTION,
            action=PreferenceAction.AVOID,
            priority=PriorityLevel.HIGH,
            category=active.category,
            key=key,
            value=new_value,
            description=f"Corrected: {active.description}",
            confidence=1.0,  # Corrections are always high confidence
            decay_policy=ConfidenceDecayPolicy.NONE,
            max_reinforcements=active.max_reinforcements,
            reinforcement_count=active.reinforcement_count,
            created_at=active.created_at,
            updated_at=now,
            last_use_at="",
            usage_count=0,
            contradicted=active.contradicted,
            contradiction_evidence=list(active.contradiction_evidence),
            corrected=True,
            correction_source=source,
            correction_reason=reason,
            deleted=False,
            tags=list(active.tags),
        )
        item.versions.append(new_version)
        self.repo.save(item)
        return item

    def delete_preference(self, key: str) -> bool:
        """Hard-delete a preference by key."""
        item_id = self._find_existing(key)
        if item_id is None:
            return False
        return self.repo.delete(item_id)

    def forget_preference(self, key: str) -> bool:
        """Soft-forget: mark as deleted but keep for audit."""
        item_id = self._find_existing(key)
        if item_id is None:
            return False
        item = self.repo.load(item_id)
        if item is None:
            return False
        active = item.active
        assert active is not None
        now = _now()
        # Mark ALL versions as deleted (item is "forgotten" — gone from lists)
        # but kept in the DB for audit trail (visible via inspect).
        for v in item.versions:
            v.deleted = True
        new_version = PreferenceVersion(
            id=item_id,
            version=active.version + 1,
            type=active.type,
            action=active.action,
            priority=active.priority,
            category=active.category,
            key=key,
            value=active.value,
            description=active.description,
            confidence=0.0,
            decay_policy=ConfidenceDecayPolicy.NONE,
            max_reinforcements=active.max_reinforcements,
            reinforcement_count=0,
            created_at=active.created_at,
            updated_at=now,
            last_use_at="",
            usage_count=0,
            contradicted=False,
            contradiction_evidence=[],
            corrected=True,
            correction_source=LearningSource.MANUAL_ENTRY,
            correction_reason="User requested forget",
            deleted=True,
            tags=list(active.tags),
        )
        item.versions.append(new_version)
        self.repo.save(item)
        return True

    # ===================================================================
    # Reinforcement & decay
    # ===================================================================

    def reinforce(self, key: str, amount: float = 0.1) -> LearningDecision:
        """Increase confidence by reinforcing (used, repeated, confirmed)."""
        item_id = self._find_existing(key)
        if item_id is None:
            return LearningDecision(action="ignored", reason=f"No preference: {key}")

        item = self.repo.load(item_id)
        if item is None:
            return LearningDecision(action="ignored", reason="Item vanished")

        active = item.active
        assert active is not None
        old_conf = active.confidence

        if active.reinforcement_count >= active.max_reinforcements:
            return LearningDecision(
                action="ignored", item_id=item_id,
                reason="Max reinforcements reached",
                old_confidence=old_conf, new_confidence=old_conf,
            )

        new_conf = min(1.0, old_conf + amount)
        now = _now()
        new_version = PreferenceVersion(
            id=item_id,
            version=active.version + 1,
            type=active.type,
            action=active.action,
            priority=active.priority,
            category=active.category,
            key=key,
            value=active.value,
            description=active.description,
            confidence=new_conf,
            decay_policy=active.decay_policy,
            created_at=active.created_at,
            updated_at=now,
            last_use_at=now,
            usage_count=active.usage_count + 1,
            contradicted=active.contradicted,
            contradiction_evidence=list(active.contradiction_evidence),
            corrected=active.corrected,
            correction_source=active.correction_source,
            correction_reason=active.correction_reason,
            deleted=active.deleted,
            tags=list(active.tags),
            reinforcement_count=active.reinforcement_count + 1,
            max_reinforcements=active.max_reinforcements,
        )
        item.versions.append(new_version)
        self.repo.save(item)
        return LearningDecision(
            action="reinforced", item_id=item_id, reason="Reinforced preference",
            old_confidence=old_conf, new_confidence=new_conf,
        )

    def decay_confidence(self) -> int:
        """Apply configured decay to all preferences and return count updated."""
        count = 0
        now = datetime.now(timezone.utc)
        for item in self.repo.list_items(include_deleted=True):
            active = item.active
            if active is None:
                continue

            if active.decay_policy == ConfidenceDecayPolicy.NONE:
                continue

            last_used = active.last_use_at
            if not last_used:
                continue

            try:
                last_dt = datetime.fromisoformat(last_used)
            except (ValueError, TypeError):
                continue

            if active.decay_policy == ConfidenceDecayPolicy.LINEAR:
                days = max(0, (now - last_dt).days)
                loss = days * self.DECAY_RATE_LINEAR
            elif active.decay_policy == ConfidenceDecayPolicy.EXPONENTIAL:
                days = max(0, (now - last_dt).days)
                weeks = days / 7.0
                loss = 1.0 - (self.DECAY_FACTOR_EXPONENTIAL ** weeks)
            else:
                continue

            new_conf = max(0.0, active.confidence - loss)
            if abs(new_conf - active.confidence) >= 0.001:
                now_ts = _now()
                new_version = PreferenceVersion(
                    id=item.id,
                    version=active.version + 1,
                    type=active.type,
                    action=active.action,
                    priority=active.priority,
                    category=active.category,
                    key=active.key,
                    value=active.value,
                    description=active.description,
                    confidence=new_conf,
                    decay_policy=active.decay_policy,
                    max_reinforcements=active.max_reinforcements,
                    reinforcement_count=active.reinforcement_count,
                    created_at=active.created_at,
                    updated_at=now_ts,
                    last_use_at=active.last_use_at,
                    usage_count=active.usage_count,
                    contradicted=active.contradicted,
                    contradiction_evidence=list(active.contradiction_evidence),
                    corrected=active.corrected,
                    correction_source=active.correction_source,
                    correction_reason=active.correction_reason,
                    deleted=active.deleted,
                    tags=list(active.tags),
                )
                item.versions.append(new_version)
                self.repo.save(item)
                count += 1
        return count

    # ===================================================================
    # Contradiction handling
    # ===================================================================

    def register_contradiction(
        self,
        key: str,
        evidence: Evidence,
    ) -> LearningDecision:
        """Record that new evidence contradicts this preference."""
        item_id = self._find_existing(key)
        if item_id is None:
            return LearningDecision(action="ignored", reason=f"No preference: {key}")

        item = self.repo.load(item_id)
        if item is None:
            return LearningDecision(action="ignored", reason="Item vanished")

        active = item.active
        assert active is not None
        old_conf = active.confidence

        new_conf = max(0.0, active.confidence - 0.3)
        now = _now()

        new_evidence = list(active.contradiction_evidence)
        new_evidence.append(evidence.to_dict())

        new_version = PreferenceVersion(
            id=item_id,
            version=active.version + 1,
            type=active.type,
            action=PreferenceAction.PROMPT,  # Promote to require confirmation
            priority=active.priority,
            category=active.category,
            key=key,
            value=active.value,
            description=active.description,
            confidence=new_conf,
            decay_policy=active.decay_policy,
            max_reinforcements=active.max_reinforcements,
            reinforcement_count=active.reinforcement_count,
            created_at=active.created_at,
            updated_at=now,
            last_use_at=active.last_use_at,
            usage_count=active.usage_count,
            contradicted=True,
            contradiction_evidence=new_evidence,
            corrected=active.corrected,
            correction_source=active.correction_source,
            correction_reason=active.correction_reason,
            deleted=active.deleted,
            tags=list(active.tags),
        )
        item.versions.append(new_version)
        self.repo.save(item)
        return LearningDecision(
            action="contradicted", item_id=item_id,
            reason="Contradiction registered",
            old_confidence=old_conf, new_confidence=new_conf,
        )

    # ===================================================================
    # Edit / Inspect
    # ===================================================================

    def edit_preference(
        self,
        key: str,
        *,
        value: str | None = None,
        description: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        source: LearningSource = LearningSource.MANUAL_ENTRY,
    ) -> LearnedItem:
        """Edit a preference, creating a new version."""
        item_id = self._find_existing(key)
        if item_id is None:
            raise KeyError(f"No preference to edit: {key}")

        item = self.repo.load(item_id)
        if item is None:
            raise KeyError(f"Item vanished: {item_id}")

        active = item.active
        assert active is not None
        now = _now()

        new_version = PreferenceVersion(
            id=item_id,
            version=active.version + 1,
            type=active.type,
            action=active.action,
            priority=active.priority,
            category=category if category is not None else active.category,
            key=key,
            value=value if value is not None else active.value,
            description=description if description is not None else active.description,
            confidence=active.confidence,
            decay_policy=active.decay_policy,
            max_reinforcements=active.max_reinforcements,
            reinforcement_count=active.reinforcement_count,
            created_at=active.created_at,
            updated_at=now,
            last_use_at=active.last_use_at,
            usage_count=active.usage_count,
            contradicted=active.contradicted,
            contradiction_evidence=list(active.contradiction_evidence),
            corrected=active.corrected,
            correction_source=active.correction_source,
            correction_reason=active.correction_reason,
            deleted=active.deleted,
            tags=tags if tags is not None else list(active.tags),
        )
        item.versions.append(new_version)
        self.repo.save(item)
        return item

    def inspect_preference(self, key: str) -> dict[str, Any]:
        """Return full details of a preference by key."""
        item_id = self._find_existing(key)
        if item_id is None:
            return {"error": "not_found", "key": key}

        item = self.repo.load(item_id)
        if item is None:
            return {"error": "not_found", "key": key}

        masked_versions = [self._mask_sensitive_version(v.to_dict()) for v in item.versions]
        return {
            "key": key,
            "id": item.id,
            "active_version": item.versions[-1].version if item.versions else 0,
            "total_versions": len(item.versions),
            "versions": masked_versions,
        }

    def list_all_preferences(self) -> list[dict]:
        """List all preferences with active details. Sensitive values are masked."""
        results = []
        for item in self.repo.list_items(include_deleted=False):
            active = item.active
            if active is None:
                continue
            d = active.to_dict()
            d["id"] = item.id
            d["versions_count"] = len(item.versions)
            d["history_available"] = len(item.versions) > 1
            results.append(self._mask_sensitive(d))
        return results

    def search_preferences(
        self, query: str, *, top_k: int = 10
    ) -> list[dict]:
        """Search preferences by key, value, description, category, or tags."""
        q = query.lower()
        all_prefs = self.list_all_preferences()
        scored: list[tuple[dict, float]] = []
        for pref in all_prefs:
            score = 0.0
            text = f"{pref['key']} {pref['value']} {pref['description']} {pref['category']} {' '.join(pref.get('tags', []))}".lower()
            if q in text:
                score += 2.0
            for word in q.split():
                if word in text:
                    score += 0.5
            if score > 0:
                scored.append((pref, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [self._mask_sensitive(p) for p, _ in scored[:top_k]]

    # ===================================================================
    # Retrieval for AgentLoop
    # ===================================================================

    def retrieve_for_decision(
        self,
        context: RetrievalContext,
    ) -> list[PreferenceMatch]:
        """Return preferences relevant to the current decision context.

        This is the hook that makes memory influence real AgentLoop decisions.
        """
        raw = self.repo.retrieve_matching(context)
        matches: list[PreferenceMatch] = []
        for item, score in raw:
            active = item.active
            if active is None or active.deleted:
                continue
            evidence = Evidence(
                text=f"Confidence {active.confidence:.2f} from {active.type.value} preference",
                context=f"retrieved for: {context.current_task[:80]}",
            )
            matches.append(PreferenceMatch(
                item=item, version=active, score=score, evidence=evidence,
            ))
        return matches

    def apply_preference_to_context(self, item: LearnedItem, context: dict) -> dict:
        """Mutate a context dict with the active preference value.

        This is called by AgentLoop when it needs to decide something.
        """
        active = item.active
        if active is None or active.deleted:
            return context

        if active.action == PreferenceAction.APPLY:
            context[f"_pref_{active.key}"] = active.value
        elif active.action == PreferenceAction.AVOID:
            context.setdefault("_pref_avoid", []).append(active.value)
        elif active.action == PreferenceAction.PROMPT:
            context.setdefault("_pref_prompt", []).append(
                {"key": active.key, "value": active.value, "reason": active.description}
            )
        elif active.action == PreferenceAction.INFORM:
            context.setdefault("_pref_info", []).append(active.value)

        return context


    # ===================================================================
    # Secret filtering & bounded storage
    # ===================================================================

    def _enforce_bounds(self) -> int:
        """Prune lowest-confidence non-explicit preferences if over limit.
        
        Returns the number of items pruned.
        """
        items = self.repo.list_items(include_deleted=True)
        active = [i for i in items if i.active and not i.active.deleted]
        if len(active) <= self.max_items:
            return 0

        # Sort by confidence ascending, prefer keeping explicit preferences
        active.sort(key=lambda i: (
            i.active.confidence,
            0 if i.active.type == PreferenceType.EXPLICIT else 1,
        ))
        
        prune_count = len(active) - self.max_items
        pruned = []
        for i in range(prune_count):
            item = active[i]
            self.repo.delete(item.id)
            pruned.append(item.key)
        return len(pruned)

    def _mask_sensitive(self, pref: dict) -> dict:
        """Mask value if the key looks like a secret."""
        from mark.preference_learning.types import _is_sensitive_key, mask_value
        if _is_sensitive_key(pref.get("key", "")):
            val = pref.get("value", "")
            if val:
                pref["value"] = mask_value(val)
                pref["value_masked"] = True
        return pref

    def _mask_sensitive_version(self, v: dict) -> dict:
        from mark.preference_learning.types import _is_sensitive_key, mask_value
        if _is_sensitive_key(v.get("key", "")):
            val = v.get("value", "")
            if val:
                v["value"] = mask_value(val)
                v["value_masked"] = True
        return v

    # ===================================================================
    # Helpers
    # ===================================================================

    def _find_existing(self, key: str) -> str | None:
        """Find an existing item by key, or None.
        
        Searches ALL items (including fully forgotten ones) so that
        operations like inspect_preference and edit can still find them.
        """
        items = self.repo.list_items(include_deleted=True)
        for item in items:
            if item.key == key and not item.active.deleted:
                return item.id
        # Also find forgotten/fully-deleted items by key alone
        for item in items:
            if item.key == key:
                return item.id
        return None


# ---------------------------------------------------------------------------
# UUID helper (avoids circular imports)
# ---------------------------------------------------------------------------

def uuid4_hex() -> str:
    return _uuid.uuid4().hex
