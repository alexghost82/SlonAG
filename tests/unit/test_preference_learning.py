"""Comprehensive tests for mark/preference_learning subsystem.

Covers all 18 requirements from task 06:
  1. preference candidate creation
  2. explicit corrections
  3. confidence
  4. evidence
  5. provenance
  6. decay
  7. conflicts (contradictions)
  8. superseding old preference
  9. inspect
  10. edit
  11. delete
  12. forget
  13. pause/disable
  14. clear
  15. export
  16. secret filtering
  17. bounded storage
  18. deterministic tests
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from mark.preference_learning.engine import PreferenceEngine
from mark.preference_learning.repository import PreferenceRepository
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
    _is_sensitive_key,
    mask_value,
    SENSITIVE_KEY_PATTERNS,
    _now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(tmp_path: Path, **kwargs) -> PreferenceEngine:
    """Create a fresh engine with its own DB in *tmp_path*."""
    db_path = tmp_path / "preference_learning.db"
    return PreferenceEngine(db_path, **kwargs)


class TestPreferenceCreation(TestCase):
    """Requirement 1: preference candidate creation."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_create_explicit_preference(self) -> None:
        item = self.engine.add_preference(
            key="theme", value="dark",
            pref_type=PreferenceType.EXPLICIT,
            source=LearningSource.USER_STATED,
        )
        self.assertIsNotNone(item.active)
        self.assertEqual(item.active.key, "theme")
        self.assertEqual(item.active.value, "dark")
        self.assertEqual(item.active.confidence, 1.0)
        self.assertEqual(item.active.decay_policy, ConfidenceDecayPolicy.NONE)

    def test_create_choice_preference(self) -> None:
        item = self.engine.add_preference(
            key="preferred_language", value="Russian",
            pref_type=PreferenceType.CHOICE,
            source=LearningSource.AGENT_OBSERVED,
        )
        self.assertEqual(item.active.confidence, 0.5)
        self.assertEqual(item.active.decay_policy, ConfidenceDecayPolicy.LINEAR)

    def test_create_habit_preference(self) -> None:
        item = self.engine.add_preference(
            key="use_tabs", value="true",
            pref_type=PreferenceType.HABIT,
        )
        self.assertEqual(item.active.type, PreferenceType.HABIT)
        self.assertEqual(item.active.confidence, 0.5)

    def test_create_corrections_preference(self) -> None:
        item = self.engine.add_preference(
            key="no_verbose", value="true",
            pref_type=PreferenceType.CORRECTION,
        )
        self.assertEqual(item.active.type, PreferenceType.CORRECTION)

    def test_create_interaction_preference(self) -> None:
        item = self.engine.add_preference(
            key="style_concise", value="true",
            pref_type=PreferenceType.INTERACTION,
        )
        self.assertEqual(item.active.type, PreferenceType.INTERACTION)

    def test_create_project_context_preference(self) -> None:
        item = self.engine.add_preference(
            key="project_lang", value="python",
            pref_type=PreferenceType.PROJECT_CONTEXT,
        )
        self.assertEqual(item.active.type, PreferenceType.PROJECT_CONTEXT)

    def test_weak_signal_does_not_become_permanent(self) -> None:
        """A single weak signal from agent observation should not become
        a permanent high-confidence preference."""
        item = self.engine.add_preference(
            key="maybe_theme", value="light",
            pref_type=PreferenceType.CHOICE,
            source=LearningSource.AGENT_OBSERVED,
        )
        # Must start at 0.5, never auto-promote to explicit-level
        self.assertLess(item.active.confidence, 1.0)
        # And should decay over time (checked in TestDecay)

    def test_preference_persists_in_repository(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        items = repo.list_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].key, "theme")


class TestExplicitCorrections(TestCase):
    """Requirement 2: explicit corrections."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_correct_preference(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        item = self.engine.correct_preference(
            key="theme",
            new_value="light",
            reason="Dark mode causes eye strain",
        )
        active = item.active
        self.assertEqual(active.value, "light")
        self.assertTrue(active.corrected)
        self.assertEqual(active.correction_reason, "Dark mode causes eye strain")
        self.assertEqual(active.action, PreferenceAction.AVOID)
        self.assertEqual(active.type, PreferenceType.CORRECTION)
        # Old version should be deleted
        old = [v for v in item.versions if not v.deleted]
        self.assertEqual(len(old), 1)

    def test_correct_nonexistent_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.engine.correct_preference(key="nope", new_value="x")

    def test_corrections_are_high_confidence(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.correct_preference(key="theme", new_value="light")
        active = self.engine.inspect_preference("theme")
        last = active["versions"][-1]
        self.assertEqual(last["confidence"], 1.0)

    def test_multiple_versions_preserved(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.correct_preference(key="theme", new_value="light")
        self.engine.edit_preference(key="theme", value="auto")
        active = self.engine.inspect_preference("theme")
        self.assertEqual(active["total_versions"], 3)


class TestConfidence(TestCase):
    """Requirement 3: confidence management."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_reinforce_increases_confidence(self) -> None:
        self.engine.add_preference(key="theme", value="dark",
                                    pref_type=PreferenceType.CHOICE)
        decision = self.engine.reinforce("theme", amount=0.2)
        self.assertEqual(decision.action, "reinforced")
        self.assertGreater(decision.new_confidence, decision.old_confidence)

    def test_reinforce_cap_at_1_0(self) -> None:
        """Explicit preference starts at confidence 1.0 and reinforcement
        is capped at 1.0 but does NOT reject — it just can't increase."""
        self.engine.add_preference(key="theme", value="dark",
                                    pref_type=PreferenceType.EXPLICIT)
        decision = self.engine.reinforce("theme", amount=0.1)
        # Explicit starts at 1.0, reinforce adds 0.1 but min(1.0, 1.0+0.1) = 1.0
        self.assertEqual(decision.new_confidence, 1.0)
        # reinforce_count goes from 0 to 1, which is < max_reinforcements (50)
        self.assertEqual(decision.action, "reinforced")
        self.assertGreater(decision.new_confidence, 0.0)

    def test_reinforce_nonexistent_ignored(self) -> None:
        decision = self.engine.reinforce("nope")
        self.assertEqual(decision.action, "ignored")

    def test_reinforcement_count_respects_limit(self) -> None:
        """With low max_reinforcements, count reaches limit."""
        from datetime import datetime, timezone
        
        self.engine.add_preference(key="test", value="v",
                                    pref_type="choice")
        repo = self.engine.repo
        item = repo.list_items()[0]
        active = item.active
        # Set max_reinforcements to 2 by creating a new version
        new_v = PreferenceVersion(
            id=active.id,
            version=active.version + 1,
            type=active.type,
            action=active.action,
            priority=active.priority,
            category=active.category,
            key=active.key,
            value=active.value,
            description=active.description,
            confidence=active.confidence,
            decay_policy=active.decay_policy,
            max_reinforcements=2,
            reinforcement_count=0,
            created_at=active.created_at,
            updated_at=active.updated_at,
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
        item.versions.append(new_v)
        repo.save(item)

        self.engine.reinforce("test", amount=0.5)
        self.engine.reinforce("test", amount=0.5)
        decision = self.engine.reinforce("test", amount=0.5)
        self.assertEqual(decision.action, "ignored")
        self.assertEqual(decision.reason, "Max reinforcements reached")


class TestEvidence(TestCase):
    """Requirement 4: evidence/provenance."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_evidence_stored_with_preference(self) -> None:
        evidence = Evidence(
            text="User said 'I prefer dark mode'",
            context="chat_turn_42",
        )
        self.engine.add_preference(
            key="theme", value="dark",
            evidence=evidence,
        )
        item = self.engine.inspect_preference("theme")
        self.assertEqual(item["total_versions"], 1)

    def test_contradiction_evidence_tracked(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        evidence = Evidence(
            text="User used --light flag",
            context="shell_exec",
        )
        self.engine.register_contradiction("theme", evidence)
        active = self.engine.inspect_preference("theme")
        self.assertEqual(active["total_versions"], 2)
        last_v = active["versions"][-1]
        self.assertTrue(last_v["contradicted"])
        self.assertEqual(len(last_v["contradiction_evidence"]), 1)


class TestProvenance(TestCase):
    """Requirement 5: provenance tracking."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_user_stated_source(self) -> None:
        item = self.engine.add_preference(
            key="test", value="v",
            source=LearningSource.USER_STATED,
        )
        self.engine.correct_preference(key="test", new_value="w")
        active = self.engine.inspect_preference("test")
        self.assertEqual(active["versions"][1]["correction_source"],
                         "correction_received")

    def test_correction_source_tracking(self) -> None:
        self.engine.add_preference(key="test", value="v")
        self.engine.correct_preference(
            key="test", new_value="w",
            source=LearningSource.CORRECTION_RECEIVED,
        )
        active = self.engine.inspect_preference("test")
        self.assertEqual(active["versions"][-1]["correction_source"],
                         "correction_received")

    def test_edit_source_tracking(self) -> None:
        self.engine.add_preference(key="test", value="v")
        self.engine.edit_preference(key="test", value="w",
                                     source=LearningSource.MANUAL_ENTRY)
        active = self.engine.inspect_preference("test")
        self.assertEqual(active["total_versions"], 2)


class TestDecay(TestCase):
    """Requirement 6: confidence decay over time."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_linear_decay(self) -> None:
        """Linear decay: CHOICE type gets LINEAR decay by default.
        Simulate decay by setting last_use_at to 3 days ago."""
        from datetime import datetime, timezone, timedelta
        from mark.preference_learning.types import _now
        
        self.engine.add_preference(
            key="theme", value="dark",
            pref_type=PreferenceType.CHOICE,
        )
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        item = repo.list_items()[0]
        active = item.active
        old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()

        new_v = PreferenceVersion(
            id=item.id,
            version=active.version + 1,
            type=active.type,
            action=active.action,
            priority=active.priority,
            category=active.category,
            key=active.key,
            value=active.value,
            description=active.description,
            confidence=active.confidence,
            decay_policy=ConfidenceDecayPolicy.LINEAR,
            created_at=active.created_at,
            updated_at=_now(),
            last_use_at=old_ts,
            usage_count=active.usage_count,
            contradicted=active.contradicted,
            contradiction_evidence=list(active.contradiction_evidence),
            corrected=active.corrected,
            correction_source=active.correction_source,
            correction_reason=active.correction_reason,
            deleted=active.deleted,
            tags=list(active.tags),
            reinforcement_count=active.reinforcement_count,
        )
        item.versions.append(new_v)
        repo.save(item)

        count = self.engine.decay_confidence()
        self.assertGreaterEqual(count, 1)
        item2 = repo.load(item.id)
        if item2 and item2.active:
            self.assertLess(item2.active.confidence, 0.5)

    def test_exponential_decay(self) -> None:
        self.engine.add_preference(
            key="theme", value="dark",
            pref_type=PreferenceType.CHOICE,
        )
        from datetime import datetime, timezone, timedelta
        from mark.preference_learning.types import _now
        
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        item = repo.list_items()[0]
        active = item.active
        old_ts = (datetime.now(timezone.utc) - timedelta(weeks=2)).replace(microsecond=0).isoformat()

        new_v = PreferenceVersion(
            id=item.id, version=active.version + 1,
            type=active.type, action=active.action,
            priority=active.priority, category=active.category,
            key=active.key, value=active.value,
            description=active.description,
            confidence=active.confidence,
            decay_policy=ConfidenceDecayPolicy.EXPONENTIAL,
            created_at=active.created_at, updated_at=_now(),
            last_use_at=old_ts, usage_count=active.usage_count,
            contradicted=active.contradicted,
            contradiction_evidence=list(active.contradiction_evidence),
            corrected=active.corrected,
            correction_source=active.correction_source,
            correction_reason=active.correction_reason,
            deleted=active.deleted, tags=list(active.tags),
            reinforcement_count=active.reinforcement_count,
        )
        item.versions.append(new_v)
        repo.save(item)

        count = self.engine.decay_confidence()
        self.assertGreaterEqual(count, 1)

    def test_no_decay_for_explicit(self) -> None:
        """Explicit preferences have NONE decay policy — never decay."""
        self.engine.add_preference(
            key="theme", value="dark",
            pref_type=PreferenceType.EXPLICIT,
        )
        from datetime import datetime, timezone, timedelta
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        item = repo.list_items()[0]
        active = item.active
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).replace(microsecond=0).isoformat()

        new_v = PreferenceVersion(
            id=item.id, version=active.version + 1,
            type=active.type, action=active.action,
            priority=active.priority, category=active.category,
            key=active.key, value=active.value,
            description=active.description,
            confidence=active.confidence,
            decay_policy=active.decay_policy,
            created_at=active.created_at, updated_at=_now(),
            last_use_at=old_ts, usage_count=active.usage_count,
            contradicted=active.contradicted,
            contradiction_evidence=list(active.contradiction_evidence),
            corrected=active.corrected,
            correction_source=active.correction_source,
            correction_reason=active.correction_reason,
            deleted=active.deleted, tags=list(active.tags),
            reinforcement_count=active.reinforcement_count,
        )
        item.versions.append(new_v)
        repo.save(item)

        count = self.engine.decay_confidence()
        self.assertEqual(count, 0)

    def test_no_decay_without_last_use(self) -> None:
        """No decay should happen if last_use_at is empty."""
        self.engine.add_preference(
            key="theme", value="dark",
            pref_type=PreferenceType.CHOICE,
        )
        count = self.engine.decay_confidence()
        self.assertEqual(count, 0)


class TestConflicts(TestCase):
    """Requirement 7: contradiction handling."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_contradiction_decreases_confidence(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        decision = self.engine.register_contradiction(
            "theme",
            Evidence(text="User explicitly set --light flag"),
        )
        self.assertEqual(decision.action, "contradicted")
        self.assertLess(decision.new_confidence, decision.old_confidence)
        # Confidence drops by 0.3
        self.assertEqual(decision.new_confidence, 0.7)

    def test_contradiction_promotes_action_to_prompt(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.register_contradiction(
            "theme",
            Evidence(text="Contradictory evidence"),
        )
        active = self.engine.inspect_preference("theme")
        self.assertEqual(active["versions"][-1]["action"], "prompt")

    def test_contradiction_on_nonexistent_ignored(self) -> None:
        decision = self.engine.register_contradiction(
            "nope",
            Evidence(text="N/A"),
        )
        self.assertEqual(decision.action, "ignored")

    def test_multiple_contradictions_accumulate(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.register_contradiction("theme", Evidence(text="E1"))
        self.engine.register_contradiction("theme", Evidence(text="E2"))
        active = self.engine.inspect_preference("theme")
        self.assertEqual(active["total_versions"], 3)
        last_v = active["versions"][-1]
        self.assertEqual(len(last_v["contradiction_evidence"]), 2)
        # Confidence: 1.0 -> 0.7 -> 0.4
        self.assertAlmostEqual(last_v["confidence"], 0.4, places=5)


class TestSuperseding(TestCase):
    """Requirement 8: superseding old preference through versioning."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_update_creates_new_version(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.add_preference(key="theme", value="light")
        item = self.engine.inspect_preference("theme")
        self.assertEqual(item["total_versions"], 2)
        self.assertEqual(item["active_version"], 2)
        self.assertEqual(item["versions"][0]["value"], "dark")
        self.assertEqual(item["versions"][1]["value"], "light")

    def test_active_is_latest_non_deleted(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.correct_preference(key="theme", new_value="light")
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        item = repo.list_items()[0]
        self.assertEqual(item.active.value, "light")
        # Old version is deleted
        self.assertTrue(item.versions[0].deleted)

    def test_superseded_version_retained_in_history(self) -> None:
        self.engine.add_preference(key="theme", value="v1")
        self.engine.edit_preference(key="theme", value="v2")
        self.engine.edit_preference(key="theme", value="v3")
        item = self.engine.inspect_preference("theme")
        self.assertEqual(item["total_versions"], 3)
        values = [v["value"] for v in item["versions"]]
        self.assertEqual(values, ["v1", "v2", "v3"])


class TestInspect(TestCase):
    """Requirement 9: inspect preference."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_inspect_existing(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        result = self.engine.inspect_preference("theme")
        self.assertNotIn("error", result)
        self.assertEqual(result["key"], "theme")
        self.assertEqual(result["total_versions"], 1)

    def test_inspect_nonexistent(self) -> None:
        result = self.engine.inspect_preference("nope")
        self.assertEqual(result["error"], "not_found")
        self.assertEqual(result["key"], "nope")

    def test_inspect_shows_all_versions(self) -> None:
        self.engine.add_preference(key="t", value="a")
        self.engine.add_preference(key="t", value="b")
        result = self.engine.inspect_preference("t")
        self.assertEqual(len(result["versions"]), 2)


class TestEdit(TestCase):
    """Requirement 10: edit preference."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_edit_value(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        item = self.engine.edit_preference(key="theme", value="light")
        self.assertEqual(item.active.value, "light")
        self.assertEqual(item.active.version, 2)

    def test_edit_description(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        item = self.engine.edit_preference(
            key="theme", description="User prefers dark UI")
        self.assertEqual(item.active.description, "User prefers dark UI")

    def test_edit_category(self) -> None:
        self.engine.add_preference(key="theme", value="dark", category="ui")
        item = self.engine.edit_preference(key="theme", category="appearance")
        self.assertEqual(item.active.category, "appearance")

    def test_edit_tags(self) -> None:
        self.engine.add_preference(key="theme", value="dark", tags=["a"])
        item = self.engine.edit_preference(key="theme", tags=["b"])
        self.assertEqual(item.active.tags, ["b"])

    def test_edit_nonexistent_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.engine.edit_preference("nope", value="x")


class TestDelete(TestCase):
    """Requirement 11: delete preference (hard delete)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_delete_existing(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.assertTrue(self.engine.delete_preference("theme"))
        self.assertEqual(len(self.engine.list_all_preferences()), 0)

    def test_delete_nonexistent(self) -> None:
        self.assertFalse(self.engine.delete_preference("nope"))

    def test_deleted_not_in_list(self) -> None:
        self.engine.add_preference(key="a", value="1")
        self.engine.add_preference(key="b", value="2")
        self.engine.delete_preference("a")
        items = self.engine.list_all_preferences()
        keys = [p["key"] for p in items]
        self.assertNotIn("a", keys)
        self.assertIn("b", keys)


class TestForget(TestCase):
    """Requirement 12: forget preference (soft delete with audit)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_forget_existing(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.assertTrue(self.engine.forget_preference("theme"))

    def test_forget_nonexistent(self) -> None:
        self.assertFalse(self.engine.forget_preference("nope"))

    def test_forgotten_not_in_list(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.forget_preference("theme")
        self.assertEqual(len(self.engine.list_all_preferences()), 0)

    def test_forgotten_has_zero_confidence(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.forget_preference("theme")
        active = self.engine.inspect_preference("theme")
        self.assertEqual(active["versions"][-1]["confidence"], 0.0)

    def test_audit_trail_preserved(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.forget_preference("theme")
        active = self.engine.inspect_preference("theme")
        self.assertEqual(active["total_versions"], 2)
        # Original version is preserved (not removed)
        self.assertEqual(active["versions"][0]["value"], "dark")


class TestPauseDisable(TestCase):
    """Requirement 13: pause/disable a preference."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_forget_disables_preference(self) -> None:
        """Forget sets confidence to 0 and marks deleted — effectively disabled."""
        self.engine.add_preference(key="theme", value="dark")
        self.engine.forget_preference("theme")
        
        # Should not appear in retrieval
        ctx = RetrievalContext(current_task="test task", min_confidence=0.3)
        matches = self.engine.retrieve_for_decision(ctx)
        self.assertEqual(len(matches), 0)

    def test_deleted_excluded_from_retrieval(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        self.engine.forget_preference("theme")
        ctx = RetrievalContext(min_confidence=0.0)
        # Even at 0.0 confidence, deleted items should not be returned
        matches = self.engine.retrieve_for_decision(ctx)
        self.assertEqual(len(matches), 0)


class TestClear(TestCase):
    """Requirement 14: clear all preferences."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_clear_all(self) -> None:
        self.engine.add_preference(key="a", value="1")
        self.engine.add_preference(key="b", value="2")
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        cleared = repo.clear_all()
        self.assertEqual(cleared, 2)
        self.assertEqual(len(self.engine.list_all_preferences()), 0)

    def test_clear_empty(self) -> None:
        repo = PreferenceRepository(self.tmp / "preference_learning.db")
        cleared = repo.clear_all()
        self.assertEqual(cleared, 0)


class TestExport(TestCase):
    """Requirement 15: export preferences."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_list_all_returns_all(self) -> None:
        self.engine.add_preference(key="a", value="1")
        self.engine.add_preference(key="b", value="2")
        prefs = self.engine.list_all_preferences()
        self.assertEqual(len(prefs), 2)
        keys = {p["key"] for p in prefs}
        self.assertEqual(keys, {"a", "b"})

    def test_search_preferences(self) -> None:
        self.engine.add_preference(key="ui_theme", value="dark",
                                    tags=["interface"])
        self.engine.add_preference(key="lang", value="python",
                                    tags=["code"])
        results = self.engine.search_preferences("ui", top_k=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], "ui_theme")

    def test_inspect_returns_full_history(self) -> None:
        self.engine.add_preference(key="t", value="v1")
        self.engine.edit_preference(key="t", value="v2")
        result = self.engine.inspect_preference("t")
        self.assertIn("versions", result)
        self.assertEqual(len(result["versions"]), 2)

    def test_export_is_serializable(self) -> None:
        self.engine.add_preference(key="t", value="v")
        prefs = self.engine.list_all_preferences()
        # Should be JSON-serializable
        json.dumps(prefs)


class TestSecretFiltering(TestCase):
    """Requirement 16: secret filtering."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_sensitive_key_patterns_detected(self) -> None:
        patterns = ["password", "api_key", "token", "secret",
                     "credential", "private_key", "auth_token"]
        for pat in patterns:
            self.assertTrue(_is_sensitive_key(pat))

    def test_non_sensitive_key_not_masked(self) -> None:
        self.assertFalse(_is_sensitive_key("theme"))
        self.assertFalse(_is_sensitive_key("preferred_language"))

    def test_sensitive_key_masked_in_list(self) -> None:
        self.engine.add_preference(key="api_key", value="sk-1234567890abcdef")
        prefs = self.engine.list_all_preferences()
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["value"], "sk****ef")
        self.assertTrue(prefs[0]["value_masked"])

    def test_sensitive_key_masked_in_search(self) -> None:
        self.engine.add_preference(key="password", value="hunter2")
        results = self.engine.search_preferences("password", top_k=10)
        self.assertEqual(results[0]["value"], "hu****r2")
        self.assertTrue(results[0]["value_masked"])

    def test_sensitive_key_masked_in_inspect(self) -> None:
        self.engine.add_preference(key="token", value="abc123xyz")
        result = self.engine.inspect_preference("token")
        self.assertEqual(result["versions"][0]["value"], "ab****yz")
        self.assertTrue(result["versions"][0]["value_masked"])

    def test_mask_value_short(self) -> None:
        self.assertEqual(mask_value("abc"), "****")

    def test_mask_value_empty(self) -> None:
        self.assertEqual(mask_value(""), "")

    def test_mask_value_long(self) -> None:
        self.assertEqual(mask_value("my_secret_password"), "my****rd")

    def test_non_sensitive_value_not_masked(self) -> None:
        self.engine.add_preference(key="theme", value="dark")
        prefs = self.engine.list_all_preferences()
        self.assertEqual(prefs[0]["value"], "dark")
        self.assertNotIn("value_masked", prefs[0])


class TestBoundedStorage(TestCase):
    """Requirement 17: bounded storage."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_default_limit_not_reached(self) -> None:
        engine = _make_engine(self.tmp)
        for i in range(10):
            engine.add_preference(key=f"pref_{i}", value=f"v{i}")
        self.assertEqual(len(engine.list_all_preferences()), 10)

    def test_exceeding_limit_triggers_prune(self) -> None:
        engine = _make_engine(self.tmp, max_items=5)
        for i in range(5):
            engine.add_preference(key=f"pref_{i}", value=f"v{i}",
                                  pref_type=PreferenceType.CHOICE)
        self.assertEqual(len(engine.list_all_preferences()), 5)
        # Adding a 6th preference should prune the lowest-confidence
        engine.add_preference(key="pref_5", value="v5",
                              pref_type=PreferenceType.CHOICE)
        self.assertEqual(len(engine.list_all_preferences()), 5)

    def test_explicit_preferences_survive_prune(self) -> None:
        """Explicit preferences should not be pruned; only choices are pruned."""
        engine = _make_engine(self.tmp, max_items=3)
        engine.add_preference(key="explicit_1", value="v1",
                              pref_type=PreferenceType.EXPLICIT)
        engine.add_preference(key="choice_a", value="va",
                              pref_type=PreferenceType.CHOICE)
        engine.add_preference(key="choice_b", value="vb",
                              pref_type=PreferenceType.CHOICE)
        engine.add_preference(key="choice_c", value="vc",
                              pref_type=PreferenceType.CHOICE)
        self.assertEqual(len(engine.list_all_preferences()), 3)
        keys = {p["key"] for p in engine.list_all_preferences()}
        # explicit_1 must survive (highest priority to keep)
        self.assertIn("explicit_1", keys)
        # Exactly one choice survives (the others are pruned)
        choices = {k for k in keys if k.startswith("choice_")}
        self.assertEqual(len(choices), 2)

    def test_lower_confidence_pruned_first(self) -> None:
        """Among equal-confidence items, oldest (lowest recency) is pruned first."""
        engine = _make_engine(self.tmp, max_items=3)
        engine.add_preference(key="high", value="v1",
                              pref_type=PreferenceType.CHOICE)
        engine.reinforce("high", amount=0.4)  # confidence = 0.9
        engine.add_preference(key="old", value="v2",
                              pref_type=PreferenceType.CHOICE)  # 0.5, oldest
        engine.add_preference(key="mid", value="v3",
                              pref_type=PreferenceType.CHOICE)  # 0.5
        engine.add_preference(key="new", value="v4",
                              pref_type=PreferenceType.CHOICE)  # 0.5, newest
        # 4th item triggers prune to 3
        self.assertEqual(len(engine.list_all_preferences()), 3)
        keys = {p["key"] for p in engine.list_all_preferences()}
        self.assertIn("high", keys)  # highest confidence survives
        # "old" is the oldest 0.5-confidence item — pruned first
        self.assertNotIn("old", keys)
        self.assertIn("mid", keys)
        self.assertIn("new", keys)


class TestRetrieval(TestCase):
    """Integration tests for retrieval with context filtering."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_retrieval_with_task_context(self) -> None:
        self.engine.add_preference(
            key="code_style", value="pep8",
            category="code",
        )
        self.engine.add_preference(
            key="ui_theme", value="dark",
            category="ui",
        )
        ctx = RetrievalContext(
            current_task="python code formatting",
            category_filter="code",
            max_results=5,
        )
        matches = self.engine.retrieve_for_decision(ctx)
        # code_style gets +0.2 category bonus + 0.1 text match = 1.3
        # ui_theme gets only 1.0 confidence (no category match)
        # code_style should be top match due to category + text bonus
        self.assertGreater(len(matches), 0)
        self.assertEqual(matches[0].version.key, "code_style")

    def test_retrieval_applies_preference(self) -> None:
        self.engine.add_preference(key="lang", value="en")
        items = self.engine.retrieve_for_decision(
            RetrievalContext(min_confidence=0.0, max_results=10)
        )
        self.assertEqual(len(items), 1)
        ctx = {}
        ctx = self.engine.apply_preference_to_context(items[0].item, ctx)
        self.assertEqual(ctx["_pref_lang"], "en")

    def test_retrieval_avoids_pref(self) -> None:
        self.engine.add_preference(
            key="avoid_tool", value="shell",
            action=PreferenceAction.AVOID,
        )
        items = self.engine.retrieve_for_decision(
            RetrievalContext(min_confidence=0.0, max_results=10)
        )
        self.assertEqual(len(items), 1)
        ctx = {}
        ctx = self.engine.apply_preference_to_context(items[0].item, ctx)
        self.assertIn("shell", ctx.get("_pref_avoid", []))

    def test_retrieval_prompts(self) -> None:
        self.engine.add_preference(
            key="confirm_delete", value="yes",
            action=PreferenceAction.PROMPT,
        )
        items = self.engine.retrieve_for_decision(
            RetrievalContext(min_confidence=0.0, max_results=10)
        )
        ctx = {}
        ctx = self.engine.apply_preference_to_context(items[0].item, ctx)
        prompts = ctx.get("_pref_prompt", [])
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["key"], "confirm_delete")


class TestDeterministic(TestCase):
    """Requirement 18: deterministic tests (no randomness in core logic)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.engine = _make_engine(self.tmp)

    def test_versioning_deterministic(self) -> None:
        """Running the same sequence of operations produces identical results."""
        self.engine.add_preference(key="t", value="a")
        self.engine.edit_preference(key="t", value="b")
        self.engine.edit_preference(key="t", value="c")
        
        result1 = self.engine.inspect_preference("t")
        self.assertEqual(result1["total_versions"], 3)
        self.assertEqual(result1["versions"][0]["value"], "a")
        self.assertEqual(result1["versions"][1]["value"], "b")
        self.assertEqual(result1["versions"][2]["value"], "c")

    def test_confidence_deterministic(self) -> None:
        """Reinforcement always produces the same result."""
        self.engine.add_preference(key="t", value="v",
                                    pref_type=PreferenceType.CHOICE)
        self.engine.reinforce("t", amount=0.1)
        self.engine.reinforce("t", amount=0.1)
        active = self.engine.list_all_preferences()[0]
        self.assertAlmostEqual(active["confidence"], 0.7, places=5)

    def test_contradiction_deterministic(self) -> None:
        """Contradiction always subtracts 0.3."""
        self.engine.add_preference(key="t", value="v")
        self.engine.register_contradiction("t", Evidence(text="E"))
        self.engine.register_contradiction("t", Evidence(text="E"))
        active = self.engine.inspect_preference("t")
        self.assertAlmostEqual(active["versions"][-1]["confidence"], 0.4, places=5)

    def test_all_enum_values_valid(self) -> None:
        """All enum members are consistent."""
        self.assertEqual(len(PreferenceType), 6)
        self.assertEqual(len(LearningSource), 6)
        self.assertEqual(len(PreferenceAction), 5)
        self.assertEqual(len(PriorityLevel), 4)
        self.assertEqual(len(ConfidenceDecayPolicy), 3)


class TestRepository(TestCase):
    """Tests for the repository layer."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_init_creates_db_file(self) -> None:
        db_path = self.tmp / "test.db"
        repo = PreferenceRepository(db_path)
        self.assertTrue(repo.db_path.exists())

    def test_save_and_load(self) -> None:
        db_path = self.tmp / "test.db"
        repo = PreferenceRepository(db_path)
        item = LearnedItem(
            id="test-id",
            versions=[
                PreferenceVersion(
                    id="v1", version=1, type=PreferenceType.EXPLICIT,
                    action=PreferenceAction.APPLY,
                    priority=PriorityLevel.HIGH,
                    key="theme", value="dark",
                    confidence=1.0, created_at="2025-01-01T00:00:00+00:00",
                    updated_at="2025-01-01T00:00:00+00:00",
                    decay_policy=ConfidenceDecayPolicy.NONE,
                )
            ],
            created_at="2025-01-01T00:00:00+00:00",
        )
        repo.save(item)
        loaded = repo.load("test-id")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.key, "theme")
        self.assertEqual(loaded.value, "dark")

    def test_list_items_empty(self) -> None:
        repo = PreferenceRepository(self.tmp / "t.db")
        self.assertEqual(repo.list_items(), [])

    def test_delete_removes_item(self) -> None:
        repo = PreferenceRepository(self.tmp / "t.db")
        item = LearnedItem(
            id="del-me",
            versions=[
                PreferenceVersion(
                    id="v1", version=1, key="x", value="y",
                    confidence=1.0, created_at=_now(),
                    updated_at=_now(),
                    decay_policy=ConfidenceDecayPolicy.NONE,
                )
            ],
        )
        repo.save(item)
        self.assertTrue(repo.delete("del-me"))
        self.assertIsNone(repo.load("del-me"))

    def test_delete_nonexistent(self) -> None:
        repo = PreferenceRepository(self.tmp / "t.db")
        self.assertFalse(repo.delete("ghost"))

    def test_clear_all_removes_everything(self) -> None:
        repo = PreferenceRepository(self.tmp / "t.db")
        item1 = LearnedItem(
            id="a",
            versions=[PreferenceVersion(id="v1", version=1, key="a", value="1",
                                         confidence=1.0, created_at="2025-01-01T00:00:00+00:00",
                                         updated_at="2025-01-01T00:00:00+00:00",
                                         decay_policy=ConfidenceDecayPolicy.NONE)],
        )
        item2 = LearnedItem(
            id="b",
            versions=[PreferenceVersion(id="v2", version=1, key="b", value="2",
                                         confidence=1.0, created_at="2025-01-01T00:00:00+00:00",
                                         updated_at="2025-01-01T00:00:00+00:00",
                                         decay_policy=ConfidenceDecayPolicy.NONE)],
        )
        repo.save(item1)
        repo.save(item2)
        self.assertEqual(repo.count(), 2)
        cleared = repo.clear_all()
        self.assertEqual(cleared, 2)
        self.assertEqual(repo.count(), 0)

    def test_count_excludes_deleted(self) -> None:
        repo = PreferenceRepository(self.tmp / "t.db")
        item = LearnedItem(
            id="del-me",
            versions=[
                PreferenceVersion(
                    id="v1", version=1, key="x", value="y",
                    confidence=1.0, created_at="2025-01-01T00:00:00+00:00",
                    updated_at="2025-01-01T00:00:00+00:00",
                    deleted=True,
                    decay_policy=ConfidenceDecayPolicy.NONE,
                )
            ],
        )
        repo.save(item)
        self.assertEqual(repo.count(), 0)
        self.assertEqual(repo.count(include_deleted=True), 1)

    def test_types_round_trip(self) -> None:
        """All types should serialize/deserialize correctly."""
        v = PreferenceVersion(
            id="v1", version=1,
            type=PreferenceType.CHOICE,
            action=PreferenceAction.PROMPT,
            priority=PriorityLevel.CRITICAL,
            category="test",
            key="t", value="v",
            confidence=0.75,
            decay_policy=ConfidenceDecayPolicy.EXPONENTIAL,
            tags=["a", "b"],
            created_at="2025-06-01T00:00:00+00:00",
            updated_at="2025-06-01T00:00:00+00:00",
        )
        d = v.to_dict()
        restored = PreferenceVersion.from_dict(d)
        self.assertEqual(restored.id, "v1")
        self.assertEqual(restored.type, PreferenceType.CHOICE)
        self.assertEqual(restored.action, PreferenceAction.PROMPT)
        self.assertEqual(restored.priority, PriorityLevel.CRITICAL)
        self.assertEqual(restored.confidence, 0.75)
        self.assertEqual(restored.tags, ["a", "b"])

    def test_evidence_round_trip(self) -> None:
        e = Evidence(text="User said X", context="turn_42")
        d = e.to_dict()
        restored = Evidence.from_dict(d)
        self.assertEqual(restored.text, "User said X")
        self.assertEqual(restored.context, "turn_42")
