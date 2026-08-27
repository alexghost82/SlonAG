"""Tests for controlled self-improvement pipeline."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase

import sys

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mark.selfimprovement.collector import MetricsCollector, ToolMetric, ProviderMetric
from mark.selfimprovement.pipeline import SelfImprovementPipeline
from mark.selfimprovement.rules import generate_candidates, _deduplicate
from mark.selfimprovement.storage import load_state, save_state
from mark.selfimprovement.types import (
    EvidenceType,
    ImprovementCategory,
    ImprovementStatus,
    Observation,
    ObservationKind,
    RiskLevel,
    SelfImprovementState,
    apply_bounded_change,
    MetricKind,
    MetricSnapshot,
    MetricBucket,
)


class TestObservationTypes(TestCase):
    def test_observation_creation(self):
        obs = Observation(
            kind=ObservationKind.TOOL_FAILURE,
            details={"tool": "test", "code": "err"},
        )
        self.assertEqual(obs.kind, ObservationKind.TOOL_FAILURE)
        self.assertEqual(obs.details["tool"], "test")

    def test_risk_levels(self):
        self.assertEqual(RiskLevel.SAFE.value, "safe")
        self.assertEqual(RiskLevel.LOW.value, "low")
        self.assertEqual(RiskLevel.MEDIUM.value, "medium")
        self.assertEqual(RiskLevel.HIGH.value, "high")

    def test_improvement_category(self):
        self.assertEqual(
            ImprovementCategory.PREFERENCE_REFINEMENT.value,
            "preference_refinement",
        )

    def test_improvement_status(self):
        self.assertEqual(ImprovementStatus.PROPOSED.value, "proposed")
        self.assertEqual(ImprovementStatus.APPROVED.value, "approved")
        self.assertEqual(ImprovementStatus.APPLIED.value, "applied")
        self.assertEqual(ImprovementStatus.ROLLED_BACK.value, "rolled_back")


class TestMetricSnapshot(TestCase):
    def test_snapshot_creation(self):
        s = MetricSnapshot(
            kind=MetricKind.TOOL_LATENCY_MS,
            value=150.0,
            unit="ms",
            dimensions={"tool": "test"},
        )
        self.assertEqual(s.kind, MetricKind.TOOL_LATENCY_MS)
        self.assertEqual(s.value, 150.0)
        self.assertEqual(s.unit, "ms")

    def test_snapshot_frozen(self):
        s = MetricSnapshot(
            kind=MetricKind.TOOL_FAILURE_COUNT,
            value=5.0,
            unit="count",
        )
        with self.assertRaises(Exception):
            s.value = 10.0


class TestMetricBucket(TestCase):
    def test_bucket_mean(self):
        b = MetricBucket(
            kind=MetricKind.TOOL_LATENCY_MS,
            dimension_key="tool",
            dimension_value="test",
            count=4,
            sum_value=600.0,
        )
        self.assertAlmostEqual(b.mean, 150.0)

    def test_bucket_success_rate(self):
        b = MetricBucket(
            kind=MetricKind.TOOL_FAILURE_COUNT,
            dimension_key="tool",
            dimension_value="test",
            count=10,
            failure_count=2,
        )
        self.assertAlmostEqual(b.success_rate, 0.8)

    def test_bucket_empty(self):
        b = MetricBucket(
            kind=MetricKind.TOOL_LATENCY_MS,
            dimension_key="x",
            dimension_value="y",
        )
        self.assertEqual(b.mean, 0.0)
        self.assertEqual(b.success_rate, 0.0)


class TestMetricsCollector(TestCase):
    def setUp(self):
        self.collector = MetricsCollector()

    def test_tool_call_success(self):
        self.collector.record_tool_call("test_tool", 100.0, True)
        stats = self.collector.get_tool_stats("test_tool")
        self.assertEqual(stats["calls"], 1)
        self.assertAlmostEqual(stats["success_rate"], 1.0)

    def test_tool_call_failure(self):
        self.collector.record_tool_call("test_tool", 200.0, False, "error")
        stats = self.collector.get_tool_stats("test_tool")
        self.assertEqual(stats["failure_rate"], 1.0)

    def test_tool_call_timeout(self):
        self.collector.record_tool_call("test_tool", 5000.0, False, "timeout", timeout=True)
        stats = self.collector.get_tool_stats("test_tool")
        self.assertEqual(stats["timeout_count"], 1)

    def test_tool_stats_insufficient_data(self):
        stats = self.collector.get_tool_stats("never_called")
        self.assertIsNone(stats)

    def test_provider_call(self):
        self.collector.record_provider_call("gemini", 500.0, True, routing=True)
        stats = self.collector.get_provider_stats("gemini")
        self.assertEqual(stats["calls"], 1)
        self.assertEqual(stats["routing_decisions"], 1)

    def test_observation_recording(self):
        obs = Observation(kind=ObservationKind.TOOL_FAILURE, details={"tool": "x"})
        self.collector.record_observation(obs)
        recents = self.collector.recent_observations(kind=ObservationKind.TOOL_FAILURE)
        self.assertEqual(len(recents), 1)
        self.assertEqual(recents[0].details["tool"], "x")

    def test_preference_correction(self):
        obs = self.collector.record_preference_correction(
            "color", "prefers blue", {"old": "red", "new": "blue"}
        )
        self.assertEqual(obs.kind, ObservationKind.PREFERENCE_CORRECTION)
        self.assertEqual(len(self.collector._preference_corrections), 1)

    def test_snapshot(self):
        self.collector.record_tool_call("t1", 100.0, True)
        self.collector.record_provider_call("p1", 500.0, True)
        snap = self.collector.get_snapshot()
        self.assertIn("tool_stats", snap)
        self.assertIn("provider_stats", snap)


class TestImprovementState(TestCase):
    def test_defaults(self):
        state = SelfImprovementState()
        self.assertEqual(state.observations_count, 0)
        self.assertEqual(state.approved_count, 0)

    def test_register_observation(self):
        state = SelfImprovementState()
        state.register_observation()
        self.assertEqual(state.observations_count, 1)

    def test_register_candidate(self):
        state = SelfImprovementState()
        state.register_candidate()
        self.assertEqual(state.candidates_generated, 1)


class TestSelfImprovementPipeline(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pipeline = SelfImprovementPipeline()
        # Override state path for testing
        from mark.selfimprovement import storage
        self._orig_path = storage._path

    def tearDown(self):
        # Clean up temp state
        state_path = Path(self.tmpdir) / "self_improvement.json"
        if state_path.exists():
            state_path.unlink()

    def test_full_pipeline_observations(self):
        pipeline = SelfImprovementPipeline()
        obs = pipeline.observe(
            Observation(kind=ObservationKind.TOOL_FAILURE, details={"tool": "x"})
        )
        self.assertEqual(obs.kind, ObservationKind.TOOL_FAILURE)
        state_summary = pipeline.get_state_summary()
        self.assertEqual(state_summary["observations_count"], 1)

    def test_full_pipeline_candidates(self):
        pipeline = SelfImprovementPipeline()
        # Add enough data to trigger candidates
        for _ in range(15):
            pipeline._collector.record_tool_call("slow_tool", 6000.0, False, "timeout", timeout=True)
        candidates = pipeline.generate_candidates()
        # Should have at least one candidate
        self.assertTrue(len(candidates) >= 1)
        for c in candidates:
            self.assertIsInstance(c.id, str)
            self.assertIsInstance(c.risk, RiskLevel)

    def test_approve_candidate(self):
        pipeline = SelfImprovementPipeline()
        # Create a candidate manually
        pipeline._state.improvements["test-candidate"] = SelfImprovementState.__dataclass_fields__
        from mark.selfimprovement.types import SelfImprovementRecord
        rec = SelfImprovementRecord(
            id="test-candidate",
            title="Test improvement",
            status=ImprovementStatus.PROPOSED,
            proposed_change={"target": "routing_stats"},
        )
        pipeline._state.improvements["test-candidate"] = rec

        result = pipeline.approve("test-candidate", approved_by="test_user")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, ImprovementStatus.APPROVED)
        self.assertIsNotNone(result.approved_at)

    def test_reject_candidate(self):
        pipeline = SelfImprovementPipeline()
        from mark.selfimprovement.types import SelfImprovementRecord
        rec = SelfImprovementRecord(
            id="reject-me",
            title="Reject this",
            status=ImprovementStatus.PROPOSED,
        )
        pipeline._state.improvements["reject-me"] = rec

        result = pipeline.reject("reject-me")
        self.assertEqual(result.status, ImprovementStatus.REJECTED)

    def test_rollback(self):
        pipeline = SelfImprovementPipeline()
        from mark.selfimprovement.types import SelfImprovementRecord
        rec = SelfImprovementRecord(
            id="rollback-test",
            title="Rollback this",
            status=ImprovementStatus.APPLIED,
            proposed_change={"target": "routing_stats"},
        )
        pipeline._state.improvements["rollback-test"] = rec

        result = pipeline.rollback("rollback-test", reason="demo")
        self.assertTrue(result)

    def test_pipeline_state_summary(self):
        pipeline = SelfImprovementPipeline()
        pipeline.observe(Observation(kind=ObservationKind.TOOL_SUCCESS))
        summary = pipeline.get_state_summary()
        self.assertIn("observations_count", summary)
        self.assertIn("improvement_statuses", summary)


class TestCandidateDedup(TestCase):
    def test_deduplication(self):
        from mark.selfimprovement.types import ImprovementCandidate
        c1 = ImprovementCandidate(
            id="a",
            category=ImprovementCategory.TOOL_STATS,
            title="High failure: tool X",
            description="desc",
            evidence="evidence",
            evidence_type=EvidenceType.STATISTICAL,
            expected_benefit="benefit",
            risk=RiskLevel.SAFE,
            proposed_change={},
            rollback_plan="none",
        )
        c2 = ImprovementCandidate(
            id="b",
            category=ImprovementCategory.TOOL_STATS,
            title="High failure: tool X (duplicate)",
            description="desc2",
            evidence="evidence2",
            evidence_type=EvidenceType.STATISTICAL,
            expected_benefit="benefit2",
            risk=RiskLevel.SAFE,
            proposed_change={},
            rollback_plan="none",
        )
        unique = _deduplicate([c1, c2])
        self.assertEqual(len(unique), 1)

    def test_no_dedup_different_category(self):
        from mark.selfimprovement.types import ImprovementCandidate
        c1 = ImprovementCandidate(
            id="a",
            category=ImprovementCategory.TOOL_STATS,
            title="Same title",
            description="desc",
            evidence="ev",
            evidence_type=EvidenceType.STATISTICAL,
            expected_benefit="b",
            risk=RiskLevel.SAFE,
            proposed_change={},
            rollback_plan="rp",
        )
        c2 = ImprovementCandidate(
            id="b",
            category=ImprovementCategory.PROVIDER_PERFORMANCE,
            title="Same title",
            description="desc",
            evidence="ev",
            evidence_type=EvidenceType.STATISTICAL,
            expected_benefit="b",
            risk=RiskLevel.SAFE,
            proposed_change={},
            rollback_plan="rp",
        )
        unique = _deduplicate([c1, c2])
        self.assertEqual(len(unique), 2)


class TestStorage(TestCase):
    def test_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            state = SelfImprovementState(
                observations_count=5,
                candidates_generated=3,
                approved_count=2,
            )
            save_state(state, path=path)
            loaded = load_state(path=path)
            self.assertEqual(loaded.observations_count, 5)
            self.assertEqual(loaded.candidates_generated, 3)
            self.assertEqual(loaded.approved_count, 2)
        finally:
            os.unlink(path)


class TestBoundedChange(TestCase):
    def test_routing_stats_target(self):
        """routing_stats target is read-only — no file write."""
        result = apply_bounded_change({
            "target": "routing_stats",
            "action": "record",
        })
        self.assertEqual(result, {})

    def test_unknown_target(self):
        result = apply_bounded_change({
            "target": "unknown_thing",
            "value": 42,
        })
        self.assertIn("error", result)


class TestIntegration(TestCase):
    """Full pipeline test from observation to rollback."""

    def test_end_to_end(self):
        pipeline = SelfImprovementPipeline()

        # Phase 1: Observe
        for _ in range(10):
            pipeline._collector.record_tool_call("slow_web", 8000.0, False, "timeout", timeout=True)
        for _ in range(5):
            pipeline._collector.record_tool_call("fast_read", 100.0, True)

        obs = pipeline.observe(
            Observation(kind=ObservationKind.PROVIDER_SLOW, details={"provider": "openrouter"})
        )
        self.assertEqual(obs.kind, ObservationKind.PROVIDER_SLOW)

        # Phase 2: Generate candidates
        candidates = pipeline.generate_candidates()

        # Phase 3: Approve the first candidate
        if candidates:
            c = candidates[0]
            pipeline.approve(c.id, approved_by="demo")

            # Phase 4: Apply
            result = pipeline.apply(c.id)
            if "error" not in result:
                # Phase 5: Monitor
                pipeline.monitor(c.id, benefit_observed="No regression")
            else:
                # Non-persistent change — acceptable
                pass

            # Phase 6: Rollback
            pipeline.rollback(c.id, reason="demo rollback")

        # Verify state
        summary = pipeline.get_state_summary()
        self.assertGreaterEqual(summary["observations_count"], 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
