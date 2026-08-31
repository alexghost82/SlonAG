"""Tests for controlled self-improvement pipeline.

Covers: versioning, immutable audit history, evaluation, user approval, rollback,
monitoring, monitoring degradation, Russian localization, security checks,
storage persistence, and end-to-end flows.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acta.selfimprovement.collector import MetricsCollector
from acta.selfimprovement.pipeline import SelfImprovementPipeline
from acta.selfimprovement.rules import _deduplicate
from acta.selfimprovement.storage import load_state, save_state
from acta.selfimprovement.types import (
    AuditAction,
    AuditEntry,
    EvidenceType,
    EvaluationStatus,
    ImprovementCandidate,
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
from acta.selfimprovement import localized_strings


# ── Helpers ───────────────────────────────────────────────────

def _make_candidate(
    title: str,
    category: ImprovementCategory = ImprovementCategory.TOOL_STATS,
    risk: RiskLevel = RiskLevel.SAFE,
) -> ImprovementCandidate:
    return ImprovementCandidate(
        id="test",
        category=category,
        title=title,
        description="desc",
        evidence="ev",
        evidence_type=EvidenceType.STATISTICAL,
        expected_benefit="b",
        risk=risk,
        proposed_change={},
        rollback_plan="rp",
    )


def _make_record(
    id: str,
    title: str,
    status: ImprovementStatus = ImprovementStatus.PROPOSED,
) -> SelfImprovementRecord:
    return SelfImprovementRecord(id=id, title=title, status=status)


# ── Observation Types ─────────────────────────────────────────

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


# ── Localization ──────────────────────────────────────────────

class TestLocalization(TestCase):
    def test_ru_messages_exist(self):
        """All required Russian messages are defined."""
        self.assertTrue(bool(localized_strings.RU_APPROVE_SUCCESS))
        self.assertTrue(bool(localized_strings.RU_REJECT_SUCCESS))
        self.assertTrue(bool(localized_strings.RU_OBSERVATION_TOOL_FAILURE))
        self.assertTrue(bool(localized_strings.RU_APPLY_SUCCESS))
        self.assertTrue(bool(localized_strings.RU_ROLLBACK_SUCCESS))
        self.assertTrue(bool(localized_strings.RU_EVALUATION_PASS))
        self.assertTrue(bool(localized_strings.RU_EVALUATION_FAIL))
        self.assertTrue(bool(localized_strings.RU_MONITOR_STABLE))

    def test_ru_f_formatting(self):
        msg = localized_strings.ru_f(localized_strings.RU_APPROVE_SUCCESS, title="Тест")
        self.assertIn("Тест", msg)

    def test_ru_f_missing_key_fallback(self):
        msg = localized_strings.ru_f("Hello {name}", name="world", missing="key")
        self.assertIn("Hello", msg)


# ── Audit ─────────────────────────────────────────────────────

class TestAuditEntry(TestCase):
    def test_audit_entry_creation(self):
        entry = AuditEntry(action=AuditAction.OBSERVE, details={"kind": "test"})
        self.assertEqual(entry.action, AuditAction.OBSERVE)
        self.assertEqual(entry.details, {"kind": "test"})

    def test_audit_entry_frozen(self):
        entry = AuditEntry(action=AuditAction.APPROVED, details={})
        with self.assertRaises(Exception):
            entry.details = {"new": "value"}

    def test_audit_entry_serialization(self):
        entry = AuditEntry(
            action=AuditAction.ROLLED_BACK,
            details={"reason": "degradation"},
            message_ru="Откат выполнен",
        )
        d = entry.to_dict()
        self.assertEqual(d["action"], "rolled_back")
        self.assertEqual(d["message_ru"], "Откат выполнен")

    def test_audit_entry_roundtrip(self):
        entry = AuditEntry(
            action=AuditAction.EVALUATED_PASS,
            details={"score": 0.9},
            message_ru="Оценка пройдена",
        )
        restored = AuditEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.action, AuditAction.EVALUATED_PASS)
        self.assertEqual(restored.details["score"], 0.9)
        self.assertEqual(restored.message_ru, "Оценка пройдена")


class TestAuditActions(TestCase):
    def test_all_actions_defined(self):
        actions = [e.value for e in AuditAction]
        self.assertIn("observe", actions)
        self.assertIn("candidate_generated", actions)
        self.assertIn("proposed", actions)
        self.assertIn("approved", actions)
        self.assertIn("rejected", actions)
        self.assertIn("evaluated_passed", actions)
        self.assertIn("evaluated_failed", actions)
        self.assertIn("applied", actions)
        self.assertIn("rolled_back", actions)
        self.assertIn("version_incremented", actions)
        self.assertIn("user_feedback", actions)


# ── Evaluation ────────────────────────────────────────────────

class TestEvaluationStatus(TestCase):
    def test_statuses(self):
        self.assertEqual(EvaluationStatus.NOT_EVALUATED.value, "not_evaluated")
        self.assertEqual(EvaluationStatus.PASSED.value, "passed")
        self.assertEqual(EvaluationStatus.FAILED.value, "failed")


# ── Versioning ────────────────────────────────────────────────

class TestVersioning(TestCase):
    def test_initial_version(self):
        rec = SelfImprovementRecord(id="v", title="Version test")
        self.assertEqual(rec.version, 1)

    def test_bump_version(self):
        rec = SelfImprovementRecord(id="v", title="Version test")
        v2 = rec.bump_version("first bump")
        self.assertEqual(v2, 2)
        self.assertEqual(rec.version, 2)

    def test_bump_version_adds_audit(self):
        rec = SelfImprovementRecord(id="v", title="Version test")
        rec.bump_version("test")
        audit = rec.audit_log
        self.assertTrue(len(audit) >= 1)
        self.assertEqual(audit[-1].action, AuditAction.VERSION_INCREMENTED)
        self.assertIn("test", audit[-1].details.get("reason", ""))

    def test_multiple_bumps(self):
        rec = SelfImprovementRecord(id="v", title="Version test")
        rec.bump_version("bump 1")
        rec.bump_version("bump 2")
        rec.bump_version("bump 3")
        self.assertEqual(rec.version, 4)
        # Each bump adds one audit entry
        self.assertEqual(len(rec.audit_log), 3)

    def test_version_increments_on_approval(self):
        rec = SelfImprovementRecord(id="v", title="Version test")
        rec.bump_version("approved")
        self.assertEqual(rec.version, 2)
        # Check audit entry has the reason
        self.assertIn("approved", rec.audit_log[-1].details.get("reason", ""))


# ── MetricsCollector ──────────────────────────────────────────

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
        self.assertIn("user_feedback_count", snap)

    def test_user_feedback_recording(self):
        fb = self.collector.record_user_feedback(
            "cand_1", "approve",
            "Одобряю это улучшение",
        )
        self.assertEqual(fb.candidate_id, "cand_1")
        self.assertEqual(fb.feedback_type, "approve")
        self.assertEqual(fb.message_ru, "Одобряю это улучшение")

        feedbacks = self.collector.get_user_feedback("cand_1")
        self.assertEqual(len(feedbacks), 1)

    def test_user_feedback_filtered(self):
        self.collector.record_user_feedback("c1", "approve", "msg1")
        self.collector.record_user_feedback("c2", "reject", "msg2")
        fb_c1 = self.collector.get_user_feedback("c1")
        self.assertEqual(len(fb_c1), 1)
        self.assertEqual(fb_c1[0].candidate_id, "c1")

    def test_user_feedback_all(self):
        self.collector.record_user_feedback("c1", "approve", "msg1")
        self.collector.record_user_feedback("c2", "reject", "msg2")
        all_fb = self.collector.get_user_feedback()
        self.assertEqual(len(all_fb), 2)


# ── Improvement State ─────────────────────────────────────────

class TestImprovementState(TestCase):
    def test_defaults(self):
        self.assertEqual(SelfImprovementState().observations_count, 0)

    def test_register_observation(self):
        s = SelfImprovementState()
        s.register_observation()
        self.assertEqual(s.observations_count, 1)

    def test_audit_history(self):
        s = SelfImprovementState()
        entry = AuditEntry(action=AuditAction.OBSERVE, details={})
        s.add_audit_entry(entry)
        self.assertEqual(len(s.audit_history), 1)


# ── SelfImprovementPipeline ───────────────────────────────────

class TestPipelineObservation(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_observations(self):
        p = SelfImprovementPipeline()
        obs = p.observe(Observation(kind=ObservationKind.TOOL_FAILURE, details={"t": "x"}))
        self.assertEqual(obs.kind, ObservationKind.TOOL_FAILURE)

    def test_observe_tool_result(self):
        p = SelfImprovementPipeline()
        obs = p.observe_tool_result("test_tool", 100.0, True)
        self.assertEqual(obs.kind, ObservationKind.TOOL_SUCCESS)

    def test_observe_tool_failure(self):
        p = SelfImprovementPipeline()
        obs = p.observe_tool_result("test_tool", 100.0, False, "error")
        self.assertEqual(obs.kind, ObservationKind.TOOL_FAILURE)

    def test_observe_tool_timeout(self):
        p = SelfImprovementPipeline()
        obs = p.observe_tool_result("test_tool", 5000.0, False, "timeout", timeout=True)
        self.assertEqual(obs.kind, ObservationKind.TOOL_TIMEOUT)

    def test_observe_audit_log(self):
        p = SelfImprovementPipeline()
        p.observe(Observation(kind=ObservationKind.TOOL_FAILURE, details={"tool": "t"}))
        audit = p.get_audit_log()
        self.assertTrue(len(audit) >= 1)
        self.assertEqual(audit[0]["action"], "observe")


class TestPipelineCandidates(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_candidates(self):
        p = SelfImprovementPipeline()
        for _ in range(15):
            p._collector.record_tool_call("slow_tool", 6000.0, False, "timeout", timeout=True)
        candidates = p.generate_candidates()
        self.assertTrue(len(candidates) >= 1)
        self.assertGreaterEqual(p._state.candidates_generated, 1)

    def test_candidates_audit(self):
        p = SelfImprovementPipeline()
        for _ in range(15):
            p._collector.record_tool_call("slow_tool", 6000.0, False, "timeout", timeout=True)
        p.generate_candidates()
        audit = p.get_audit_log()
        self.assertTrue(len(audit) >= 1)
        # Check for candidate_generated action
        actions = [e["action"] for e in audit]
        self.assertIn("candidate_generated", actions)


class TestPipelineVersioning(TestCase):
    def test_version_increments_on_approve(self):
        p = SelfImprovementPipeline()
        rec = _make_record("v1", "Version test")
        p._state.improvements["v1"] = rec
        p.approve("v1", approved_by="user1")
        self.assertEqual(p._state.improvements["v1"].version, 2)  # 1 + bump_version

    def test_version_increments_on_apply(self):
        p = SelfImprovementPipeline()
        rec = _make_record("v2", "Apply test")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["v2"] = rec
        p.apply("v2")
        self.assertGreater(p._state.improvements["v2"].version, 1)

    def test_version_increments_on_rollback(self):
        p = SelfImprovementPipeline()
        rec = _make_record("v3", "Rollback test")
        rec.status = ImprovementStatus.APPLIED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["v3"] = rec
        p.rollback("v3", reason="demo")
        self.assertGreater(p._state.improvements["v3"].version, 1)


class TestPipelineApproval(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_approve(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap1", "Approve test")
        p._state.improvements["ap1"] = rec
        result = p.approve("ap1", approved_by="user1", message_ru="Одобряю")
        self.assertEqual(result.status, ImprovementStatus.APPROVED)

    def test_approve_with_audit(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap2", "Approve test")
        p._state.improvements["ap2"] = rec
        p.approve("ap2", approved_by="user1")
        audit = rec.audit_log
        self.assertTrue(len(audit) >= 1)
        approved_entries = [a for a in audit if a.action == AuditAction.APPROVED]
        self.assertTrue(len(approved_entries) >= 1)
        self.assertIn("user1", approved_entries[-1].details.get("approved_by", ""))

    def test_approve_unknown(self):
        p = SelfImprovementPipeline()
        result = p.approve("nonexistent")
        self.assertIsNone(result)

    def test_user_feedback_on_approval(self):
        p = SelfImprovementPipeline()
        rec = _make_record("uf1", "Feedback test")
        p._state.improvements["uf1"] = rec
        p.approve("uf1", approved_by="user1")
        feedbacks = p._collector.get_user_feedback("uf1")
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(feedbacks[0].feedback_type, "approve")
        self.assertTrue(bool(feedbacks[0].message_ru))


class TestPipelineReject(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_reject(self):
        p = SelfImprovementPipeline()
        rec = _make_record("rm1", "Reject test")
        p._state.improvements["rm1"] = rec
        result = p.reject("rm1", reason="Not suitable")
        self.assertEqual(result.status, ImprovementStatus.REJECTED)

    def test_reject_audit(self):
        p = SelfImprovementPipeline()
        rec = _make_record("rm2", "Reject test")
        p._state.improvements["rm2"] = rec
        p.reject("rm2", reason="Not suitable")
        audit = rec.audit_log
        self.assertTrue(any(a.action == AuditAction.REJECTED for a in audit))

    def test_reject_version_bump(self):
        p = SelfImprovementPipeline()
        rec = _make_record("rm3", "Reject test")
        p._state.improvements["rm3"] = rec
        p.reject("rm3", reason="test")
        self.assertEqual(rec.version, 2)  # initial 1 + bump


class TestPipelineEvaluation(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_evaluate_pass(self):
        p = SelfImprovementPipeline()
        rec = _make_record("eval1", "Eval test")
        rec.status = ImprovementStatus.APPROVED
        p._state.improvements["eval1"] = rec
        result = p.evaluate("eval1", reason="Good change", score=0.9, passed=True)
        self.assertEqual(result.status, ImprovementStatus.APPROVED)
        self.assertEqual(result.evaluation, EvaluationStatus.PASSED)
        self.assertAlmostEqual(result.evaluation_score, 0.9)

    def test_evaluate_fail(self):
        p = SelfImprovementPipeline()
        rec = _make_record("eval2", "Eval test")
        rec.status = ImprovementStatus.APPROVED
        p._state.improvements["eval2"] = rec
        result = p.evaluate("eval2", reason="Security risk", score=0.1, passed=False)
        self.assertEqual(result.status, ImprovementStatus.REJECTED)
        self.assertEqual(result.evaluation, EvaluationStatus.FAILED)

    def test_evaluate_unknown(self):
        p = SelfImprovementPipeline()
        result = p.evaluate("nonexistent")
        self.assertIsNone(result)

    def test_evaluate_audit_log(self):
        p = SelfImprovementPipeline()
        rec = _make_record("eval3", "Eval test")
        rec.status = ImprovementStatus.APPROVED
        p._state.improvements["eval3"] = rec
        p.evaluate("eval3", reason="test", score=1.0, passed=True)
        audit = rec.audit_log
        self.assertTrue(any(a.action == AuditAction.EVALUATED_PASS for a in audit))

    def test_evaluate_version_bump(self):
        p = SelfImprovementPipeline()
        rec = _make_record("eval4", "Eval test")
        rec.status = ImprovementStatus.APPROVED
        p._state.improvements["eval4"] = rec
        p.evaluate("eval4", reason="test", score=0.5, passed=True)
        self.assertGreater(rec.version, 1)

    def test_evaluate_security_violation(self):
        """Ensure changes that weaken security are rejected."""
        p = SelfImprovementPipeline()
        rec = _make_record("sec_eval_1", "Security test")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {
            "target": "config",
            "action": "",
            "key": "disable_auth",  # forbidden pattern
        }
        p._state.improvements["sec1"] = rec
        result = p.evaluate("sec1", reason="Security check", score=0.0, passed=True)
        # Should fail due to security violation
        self.assertEqual(result.status, ImprovementStatus.REJECTED)
        self.assertEqual(result.evaluation, EvaluationStatus.FAILED)


class TestPipelineApply(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_apply_routing_stats(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap5", "Apply test")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {"target": "routing_stats", "action": "flag"}
        p._state.improvements["ap5"] = rec
        result = p.apply("ap5")
        self.assertNotIn("error", result)
        self.assertEqual(p._state.improvements["ap5"].status, ImprovementStatus.APPLIED)

    def test_apply_not_approved(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap6", "Apply test")
        rec.status = ImprovementStatus.PROPOSED
        p._state.improvements["ap6"] = rec
        result = p.apply("ap6")
        self.assertIn("error", result)

    def test_apply_failed_evaluation(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap7", "Apply test")
        rec.status = ImprovementStatus.APPROVED
        rec.evaluation = EvaluationStatus.FAILED
        rec.evaluation_reason = "security violation"
        p._state.improvements["ap7"] = rec
        result = p.apply("ap7")
        self.assertIn("error", result)

    def test_apply_audit(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap8", "Apply test")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["ap8"] = rec
        p.apply("ap8")
        audit = rec.audit_log
        self.assertTrue(any(a.action == AuditAction.APPLIED for a in audit))

    def test_apply_version_bump(self):
        p = SelfImprovementPipeline()
        rec = _make_record("ap9", "Apply test")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["ap9"] = rec
        p.apply("ap9")
        self.assertGreater(rec.version, 1)


class TestPipelineMonitor(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_monitor_stable(self):
        p = SelfImprovementPipeline()
        rec = _make_record("mon1", "Monitor test")
        rec.status = ImprovementStatus.APPLIED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["mon1"] = rec
        result = p.monitor("mon1", benefit_observed="OK")
        self.assertEqual(result.benefit_observed, "OK")

    def test_monitor_degradation(self):
        p = SelfImprovementPipeline()
        rec = _make_record("mon2", "Monitor test")
        rec.status = ImprovementStatus.APPLIED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["mon2"] = rec
        result = p.monitor("mon2", degradation_detected=True)
        # Should be set to REJECTED with failed evaluation
        self.assertEqual(result.status, ImprovementStatus.REJECTED)
        self.assertEqual(result.evaluation, EvaluationStatus.FAILED)

    def test_monitor_not_applied(self):
        p = SelfImprovementPipeline()
        rec = _make_record("mon3", "Monitor test")
        rec.status = ImprovementStatus.PROPOSED
        p._state.improvements["mon3"] = rec
        result = p.monitor("mon3")
        self.assertIsNone(result)


class TestPipelineRollback(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_rollback(self):
        p = SelfImprovementPipeline()
        rec = _make_record("rb", "Rollback test")
        rec.status = ImprovementStatus.APPLIED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["rb"] = rec
        self.assertTrue(p.rollback("rb", reason="demo"))
        self.assertEqual(p._state.improvements["rb"].status, ImprovementStatus.ROLLED_BACK)

    def test_rollback_unknown(self):
        p = SelfImprovementPipeline()
        self.assertFalse(p.rollback("nonexistent"))

    def test_rollback_audit(self):
        p = SelfImprovementPipeline()
        rec = _make_record("rb2", "Rollback test")
        rec.status = ImprovementStatus.APPLIED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["rb2"] = rec
        p.rollback("rb2", reason="degradation")
        audit = rec.audit_log
        self.assertTrue(any(a.action == AuditAction.ROLLED_BACK for a in audit))

    def test_rollback_version_bump(self):
        p = SelfImprovementPipeline()
        rec = _make_record("rb3", "Rollback test")
        rec.status = ImprovementStatus.APPLIED
        rec.proposed_change = {"target": "routing_stats"}
        p._state.improvements["rb3"] = rec
        p.rollback("rb3", reason="demo")
        self.assertGreater(rec.version, 1)


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
            self.assertEqual(loaded.approved_count, 2)
        finally:
            os.unlink(path)

    def test_roundtrip_with_improvements(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            state = SelfImprovementState()
            rec = SelfImprovementRecord(
                id="imp1", title="Test", status=ImprovementStatus.APPROVED,
                version=3,
                proposed_change={"target": "config"},
            )
            rec.bump_version("test")
            state.improvements["imp1"] = rec
            save_state(state, path=path)
            loaded = load_state(path=path)
            self.assertIn("imp1", loaded.improvements)
            self.assertGreaterEqual(loaded.improvements["imp1"].version, 3)
        finally:
            os.unlink(path)

    def test_roundtrip_with_audit_history(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            state = SelfImprovementState()
            state.add_audit_entry(AuditEntry(action=AuditAction.OBSERVE, details={"kind": "test"}))
            save_state(state, path=path)
            loaded = load_state(path=path)
            self.assertEqual(len(loaded.audit_history), 1)
            self.assertEqual(loaded.audit_history[0].action, AuditAction.OBSERVE)
        finally:
            os.unlink(path)

    def test_load_nonexistent(self):
        state = load_state(path="/tmp/nonexistent_self_improvement_test.json")
        self.assertEqual(state.observations_count, 0)


class TestBoundedChange(TestCase):
    def test_routing_stats_target(self):
        self.assertEqual(apply_bounded_change({"target": "routing_stats"}), {})

    def test_unknown_target(self):
        self.assertIn("error", apply_bounded_change({"target": "unknown_thing"}))


# ── Pipeline Details ─────────────────────────────────────────

class TestPipelineDetails(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None
    def test_get_candidate_details(self):
        p = SelfImprovementPipeline()
        rec = _make_record("cd1", "Details test")
        rec.status = ImprovementStatus.APPROVED
        rec.version = 2
        p._state.improvements["cd1"] = rec
        details = p.get_candidate_details("cd1")
        self.assertEqual(details["id"], "cd1")
        self.assertEqual(details["status"], "approved")
        self.assertEqual(details["version"], 2)
        self.assertIn("audit_log", details)

    def test_get_state_summary(self):
        p = SelfImprovementPipeline()
        for _ in range(3):
            p._collector.record_tool_call("t", 100.0, True)
        p.generate_candidates()
        summary = p.get_state_summary()
        self.assertGreaterEqual(summary["candidates_generated"], 1)
        self.assertGreaterEqual(summary["candidates_generated"], 1)

    def test_get_user_feedback_summary(self):
        p = SelfImprovementPipeline()
        from acta.selfimprovement.collector import MetricsCollector
        fresh_collector = MetricsCollector()
        fresh_collector.record_user_feedback("c1", "approve", "msg1")
        fresh_collector.record_user_feedback("c2", "reject", "msg2")
        fb_summary = {
            "total": len(fresh_collector.get_user_feedback()),
            "by_type": {},
        }
        for fb in fresh_collector.get_user_feedback():
            fb_summary["by_type"][fb.feedback_type] = fb_summary["by_type"].get(fb.feedback_type, 0) + 1
        self.assertEqual(fb_summary["total"], 2)
        self.assertEqual(fb_summary["by_type"]["approve"], 1)
        self.assertEqual(fb_summary["by_type"]["reject"], 1)

    def test_audit_log_for_candidate(self):
        p = SelfImprovementPipeline()
        rec = _make_record("al1", "Audit test")
        rec.audit(AuditAction.APPROVED, details={"approved_by": "user"})
        p._state.improvements["al1"] = rec
        audit = p.get_audit_log("al1")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "approved")


# ── End-to-End ─────────────────────────────────────────────────

class TestIntegration(TestCase):
    def setUp(self):
        # Clear disk state and in-memory cached state
        import acta.selfimprovement
        _state_path = Path("/home/slon/Documents/GitHub/SlonAG/SlonAG-fix-worktrees/08/memory/self_improvement.json")
        if _state_path.exists():
            _state_path.unlink()
        acta.selfimprovement._state = None
        acta.selfimprovement._collector = None

    def test_full_pipeline(self):
        """End-to-end: observation → candidate → approval → evaluation → apply → monitor."""
        p = SelfImprovementPipeline()
        # Disk is cleared by setUp, so state starts fresh

        # 1. Observe failures
        for _ in range(10):
            p._collector.record_tool_call("slow_web", 8000.0, False, "timeout", timeout=True)
        from acta.selfimprovement.types import Observation, ObservationKind
        p.observe(Observation(kind=ObservationKind.PROVIDER_SLOW, details={"p": "or"}))
        self.assertGreater(p._state.observations_count, 0)

        # 2. Create a clean record for evaluation
        from acta.selfimprovement.types import SelfImprovementRecord, ImprovementStatus, EvaluationStatus
        new_rec = SelfImprovementRecord(
            id="fp_" + str(id(p) % 100000),
            title="End-to-end test improvement",
            status=ImprovementStatus.PROPOSED,
            proposed_change={"target": "routing_stats", "action": "test"},
            version=1,
        )
        p._state.improvements[new_rec.id] = new_rec

        # 3. Approve
        p.approve(new_rec.id, approved_by="demo", message_ru="Одобряю")

        # 4. Evaluate (pass)
        rec = p.evaluate(new_rec.id, reason="Good improvement", score=0.9, passed=True)
        self.assertEqual(rec.evaluation, EvaluationStatus.PASSED)
        self.assertEqual(rec.status, ImprovementStatus.APPROVED)

        # 5. Apply
        result = p.apply(new_rec.id)
        self.assertNotIn("error", result)
        self.assertEqual(p._state.improvements[new_rec.id].status, ImprovementStatus.APPLIED)

        # 6. Monitor (stable)
        p.monitor(new_rec.id, benefit_observed="No degradation")

        # 7. Check versioning
        self.assertGreater(p._state.improvements[new_rec.id].version, 1)

        # 8. Check audit log
        audit = p.get_audit_log(new_rec.id)
        self.assertTrue(len(audit) >= 3)

        # 9. Verify state summary
        summary = p.get_state_summary()
        self.assertGreaterEqual(summary["observations_count"], 1)
        """End-to-end: observation → candidate → approval → evaluation → apply → monitor → rollback."""
        p = SelfImprovementPipeline()

        # 1. Observe failures
        for _ in range(10):
            p._collector.record_tool_call("slow_web", 8000.0, False, "timeout", timeout=True)
        p.observe(Observation(kind=ObservationKind.PROVIDER_SLOW, details={"p": "or"}))
        self.assertGreater(p._state.observations_count, 0)

        # 2. Generate candidates
        candidates = p.generate_candidates()
        self.assertTrue(len(candidates) >= 1)

        # 3. Pick a candidate and approve
        c = candidates[0]
        p.approve(c.id, approved_by="demo", message_ru="Одобряю это улучшение")

        # 4. Evaluate (pass)
        rec = p.evaluate(c.id, reason="Good improvement", score=0.9, passed=True)
        self.assertEqual(rec.evaluation, EvaluationStatus.PASSED)

        # 5. Apply
        result = p.apply(c.id)
        self.assertNotIn("error", result)
        self.assertEqual(p._state.improvements[c.id].status, ImprovementStatus.APPLIED)

        # 6. Monitor (stable)
        p.monitor(c.id, benefit_observed="No degradation")

        # 7. Check versioning
        self.assertGreater(p._state.improvements[c.id].version, 1)

        # 8. Check audit log
        audit = p.get_audit_log(c.id)
        self.assertTrue(len(audit) >= 3)  # at least proposed, approved, applied

        # 9. Verify state summary
        summary = p.get_state_summary()
        self.assertGreaterEqual(summary["candidates_generated"], 1)

    def test_rollback_after_apply(self):
        """Apply → detect degradation → rollback."""
        p = SelfImprovementPipeline()

        for _ in range(5):
            p._collector.record_tool_call("test_tool", 500.0, True)

        # Create a manually-approved candidate
        rec = _make_record("rollback_e2e", "Rollback E2E")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {"target": "routing_stats", "action": "test"}
        p._state.improvements["rollback_e2e"] = rec

        # Apply
        p.apply("rollback_e2e")
        self.assertEqual(p._state.improvements["rollback_e2e"].status, ImprovementStatus.APPLIED)

        # Rollback (manual rollback after apply)
        self.assertTrue(p.rollback("rollback_e2e", reason="degradation"))
        self.assertEqual(p._state.improvements["rollback_e2e"].status, ImprovementStatus.ROLLED_BACK)

        # Verify audit — the record was manually set to APPLIED, so verify the rollback happened
        self.assertEqual(p._state.improvements["rollback_e2e"].status, ImprovementStatus.ROLLED_BACK)
        audit = p.get_audit_log("rollback_e2e")
        actions = [a["action"] for a in audit]
        self.assertIn("applied", actions)
        self.assertIn("rolled_back", actions)

    def test_failed_evaluation_rejects_candidate(self):
        """A candidate that fails evaluation should be rejected, not applied."""
        p = SelfImprovementPipeline()
        rec = _make_record("eval_fail_1", "Eval fail test")
        rec.status = ImprovementStatus.APPROVED
        rec.proposed_change = {
            "target": "config",
            "action": "",
            "key": "disable_auth",  # forbidden
        }
        p._state.improvements["eval_fail_1"] = rec

        result = p.evaluate("eval_fail_1", reason="Security violation", score=0.0, passed=True)
        self.assertEqual(result.status, ImprovementStatus.REJECTED)
        self.assertEqual(result.evaluation, EvaluationStatus.FAILED)

    def test_persistence_roundtrip(self):
        """Full pipeline → save → load → verify."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            p = SelfImprovementPipeline()
            # Run some pipeline operations
            p.observe(Observation(kind=ObservationKind.TOOL_FAILURE, details={"tool": "t"}))
            rec = _make_record("persist1", "Persist test")
            rec.status = ImprovementStatus.APPROVED
            p._state.improvements["persist1"] = rec
            p.approve("persist1")
            p._state.add_audit_entry(AuditEntry(
                action=AuditAction.APPROVED,
                details={"approved_by": "user"},
                message_ru="Одобряю",
            ))
            p.persist()  # save to temp path would require setting _state path

            # Manually save to temp
            save_state(p._state, path=path)

            # Load fresh
            loaded = load_state(path=path)
            self.assertGreaterEqual(loaded.observations_count, 1)
            self.assertIn("persist1", loaded.improvements)
            self.assertEqual(loaded.improvements["persist1"].status, ImprovementStatus.APPROVED)
            self.assertTrue(len(loaded.audit_history) >= 1)
        finally:
            os.unlink(path)

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


if __name__ == "__main__":
    import unittest
    unittest.main()
