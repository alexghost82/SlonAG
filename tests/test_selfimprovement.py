"""Tests for controlled self-improvement pipeline."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mark.selfimprovement.collector import MetricsCollector
from mark.selfimprovement.pipeline import SelfImprovementPipeline
from mark.selfimprovement.rules import _deduplicate
from mark.selfimprovement.storage import load_state, save_state
from mark.selfimprovement.types import (
    EvidenceType,
    ImprovementCategory,
    ImprovementStatus,
    Observation,
    ObservationKind,
    RiskLevel,
    SelfImprovementState,
    SelfImprovementRecord,
    apply_bounded_change,
    MetricKind,
    MetricSnapshot,
    MetricBucket,
)


class TestObservationTypes(TestCase):
    def test_observation_creation(self):
        obs = Observation(kind=ObservationKind.TOOL_FAILURE, details={"tool": "test"})
        self.assertEqual(obs.kind, ObservationKind.TOOL_FAILURE)

    def test_risk_levels(self):
        self.assertEqual(RiskLevel.SAFE.value, "safe")
        self.assertEqual(RiskLevel.LOW.value, "low")

    def test_improvement_category(self):
        self.assertEqual(ImprovementCategory.PREFERENCE_REFINEMENT.value, "preference_refinement")

    def test_improvement_status(self):
        self.assertEqual(ImprovementStatus.PROPOSED.value, "proposed")


class TestMetricSnapshot(TestCase):
    def test_snapshot_creation(self):
        s = MetricSnapshot(kind=MetricKind.TOOL_LATENCY_MS, value=150.0, unit="ms")
        self.assertEqual(s.kind, MetricKind.TOOL_LATENCY_MS)

    def test_snapshot_frozen(self):
        s = MetricSnapshot(kind=MetricKind.TOOL_FAILURE_COUNT, value=5.0, unit="count")
        with self.assertRaises(Exception):
            s.value = 10.0


class TestMetricBucket(TestCase):
    def test_bucket_mean(self):
        b = MetricBucket(kind=MetricKind.TOOL_LATENCY_MS, dimension_key="t",
                         dimension_value="v", count=4, sum_value=600.0)
        self.assertAlmostEqual(b.mean, 150.0)

    def test_bucket_success_rate(self):
        b = MetricBucket(kind=MetricKind.TOOL_FAILURE_COUNT, dimension_key="t",
                         dimension_value="v", count=10, failure_count=2)
        self.assertAlmostEqual(b.success_rate, 0.8)


class TestMetricsCollector(TestCase):
    def setUp(self):
        self.collector = MetricsCollector()

    def test_tool_call_success(self):
        self.collector.record_tool_call("t", 100.0, True)
        stats = self.collector.get_tool_stats("t")
        self.assertEqual(stats["calls"], 1)
        self.assertAlmostEqual(stats["success_rate"], 1.0)

    def test_tool_call_failure(self):
        self.collector.record_tool_call("t", 200.0, False, "error")
        stats = self.collector.get_tool_stats("t")
        self.assertAlmostEqual(stats["failure_rate"], 1.0)

    def test_tool_call_timeout(self):
        self.collector.record_tool_call("t", 5000.0, False, "timeout", timeout=True)
        stats = self.collector.get_tool_stats("t")
        self.assertEqual(stats["timeout_count"], 1)

    def test_provider_call(self):
        self.collector.record_provider_call("gemini", 500.0, True, routing_decision=True)
        stats = self.collector.get_provider_stats("gemini")
        self.assertEqual(stats["routing_decisions"], 1)

    def test_preference_correction(self):
        obs = self.collector.record_preference_correction("color", "prefers blue")
        self.assertEqual(obs.kind, ObservationKind.PREFERENCE_CORRECTION)

    def test_snapshot(self):
        self.collector.record_tool_call("t1", 100.0, True)
        self.collector.record_provider_call("p1", 500.0, True)
        snap = self.collector.get_snapshot()
        self.assertIn("tool_stats", snap)


class TestImprovementState(TestCase):
    def test_defaults(self):
        self.assertEqual(SelfImprovementState().observations_count, 0)

    def test_register_observation(self):
        s = SelfImprovementState()
        s.register_observation()
        self.assertEqual(s.observations_count, 1)


class TestSelfImprovementPipeline(TestCase):
    def test_observations(self):
        p = SelfImprovementPipeline()
        obs = p.observe(Observation(kind=ObservationKind.TOOL_FAILURE, details={"t": "x"}))
        self.assertEqual(obs.kind, ObservationKind.TOOL_FAILURE)

    def test_candidates(self):
        p = SelfImprovementPipeline()
        for _ in range(15):
            p._collector.record_tool_call("slow_tool", 6000.0, False, "timeout", timeout=True)
        candidates = p.generate_candidates()
        self.assertTrue(len(candidates) >= 1)

    def test_approve(self):
        p = SelfImprovementPipeline()
        rec = SelfImprovementRecord(id="tc", title="Test", status=ImprovementStatus.PROPOSED,
                                     proposed_change={"target": "routing_stats"})
        p._state.improvements["tc"] = rec
        result = p.approve("tc")
        self.assertEqual(result.status, ImprovementStatus.APPROVED)

    def test_reject(self):
        p = SelfImprovementPipeline()
        rec = SelfImprovementRecord(id="rm", title="Reject", status=ImprovementStatus.PROPOSED)
        p._state.improvements["rm"] = rec
        result = p.reject("rm")
        self.assertEqual(result.status, ImprovementStatus.REJECTED)

    def test_rollback(self):
        p = SelfImprovementPipeline()
        rec = SelfImprovementRecord(id="rb", title="Rollback", status=ImprovementStatus.APPLIED,
                                     proposed_change={"target": "routing_stats"})
        p._state.improvements["rb"] = rec
        self.assertTrue(p.rollback("rb", reason="demo"))


class TestCandidateDedup(TestCase):
    def test_deduplication(self):
        c1 = _make_candidate("This is a very long title that exceeds forty characters for dedup testing")
        c2 = _make_candidate("This is a very long title that exceeds forty characters for dedup testing v2")
        unique = _deduplicate([c1, c2])
        self.assertEqual(len(unique), 1)

    def test_no_dedup_different_category(self):
        c1 = _make_candidate("Same title", category=ImprovementCategory.TOOL_STATS)
        c2 = _make_candidate("Same title", category=ImprovementCategory.PROVIDER_PERFORMANCE)
        unique = _deduplicate([c1, c2])
        self.assertEqual(len(unique), 2)


class TestStorage(TestCase):
    def test_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_state(SelfImprovementState(observations_count=5, candidates_generated=3, approved_count=2), path=path)
            loaded = load_state(path=path)
            self.assertEqual(loaded.observations_count, 5)
        finally:
            os.unlink(path)


class TestBoundedChange(TestCase):
    def test_routing_stats_target(self):
        self.assertEqual(apply_bounded_change({"target": "routing_stats"}), {})

    def test_unknown_target(self):
        self.assertIn("error", apply_bounded_change({"target": "unknown_thing"}))


class TestIntegration(TestCase):
    def test_end_to_end(self):
        p = SelfImprovementPipeline()
        for _ in range(10):
            p._collector.record_tool_call("slow_web", 8000.0, False, "timeout", timeout=True)
        p.observe(Observation(kind=ObservationKind.PROVIDER_SLOW, details={"p": "or"}))
        candidates = p.generate_candidates()
        if candidates:
            c = candidates[0]
            p.approve(c.id, approved_by="demo")
            p.apply(c.id)
            p.rollback(c.id, reason="demo")
        self.assertGreaterEqual(p.get_state_summary()["observations_count"], 1)


def _make_candidate(title: str,
                    category: ImprovementCategory = ImprovementCategory.TOOL_STATS) -> ImprovementCandidate:
    return ImprovementCandidate(
        id="test", category=category, title=title, description="desc", evidence="ev",
        evidence_type=EvidenceType.STATISTICAL, expected_benefit="b", risk=RiskLevel.SAFE,
        proposed_change={}, rollback_plan="rp",
    )


if __name__ == "__main__":
    import unittest
    unittest.main()
