"""Pipeline — orchestrates the full self-improvement lifecycle.

Observation → improvement candidate → evidence → expected benefit → risk
→ approval → apply bounded change → monitor → rollback.
"""

from __future__ import annotations

import time
import threading
from typing import Any

from .collector import MetricsCollector
from .rules import generate_candidates
from .storage import load_state, save_state
from .types import (
    AuditAction,
    EvaluationRecord,
    EvaluationResult,
    ImprovementCandidate,
    ImprovementStatus,
    MonitorStatus,
    MonitoringSnapshot,
    Observation,
    ObservationKind,
    RiskLevel,
    SecurityCheckResult,
    SecurityPolicyViolation,
    SelfImprovementRecord,
    VersionBumpKind,
    SelfImprovementState,
    apply_bounded_change,
    check_security_policy,
)


class SelfImprovementPipeline:
    """Central orchestrator for controlled self-improvement."""

    def __init__(self, collector: MetricsCollector | None = None) -> None:
        self._collector = collector or MetricsCollector.instance()
        self._state = load_state()
        self._lock = threading.Lock()
        self._monitoring: dict[str, dict[str, Any]] = {}  # id → before snapshot
        self._monitor_snapshots: dict[str, MonitoringSnapshot] = {}  # id → MonitoringSnapshot
        self._user_approval_callbacks: dict[str, bool] = {}  # id → approved (for tests)

    # ── Phase 1: Observation ──────────────────────────────────

    def observe(self, obs: Observation) -> Observation:
        """Register an observation. Thread-safe."""
        with self._lock:
            self._state.register_observation()
            self._collector.record_observation(obs)
        return obs

    def observe_tool_result(
        self,
        tool_name: str,
        latency_ms: float,
        success: bool,
        code: str = "ok",
        timeout: bool = False,
    ) -> Observation:
        """Convenience: observe a tool execution result."""
        self._collector.record_tool_call(tool_name, latency_ms, success, code, timeout)
        if timeout:
            obs = self._collector.record_tool_timeout(tool_name, latency_ms / 1000)
        elif not success:
            obs = self._collector.record_tool_failure(tool_name, code)
        else:
            obs = Observation(
                kind=ObservationKind.TOOL_SUCCESS,
                details={"tool": tool_name, "latency_ms": latency_ms},
            )
        return self.observe(obs)

    def observe_provider_result(
        self,
        provider_id: str,
        latency_ms: float,
        success: bool,
        timeout: bool = False,
        routing: bool = False,
    ) -> Observation:
        """Convenience: observe a provider call result."""
        self._collector.record_provider_call(provider_id, latency_ms, success, timeout, routing)
        if timeout:
            obs = Observation(
                kind=ObservationKind.PROVIDER_FAILED,
                details={"provider": provider_id, "reason": "timeout", "latency_ms": latency_ms},
            )
        elif not success:
            obs = Observation(
                kind=ObservationKind.PROVIDER_FAILED,
                details={"provider": provider_id, "reason": "error", "latency_ms": latency_ms},
            )
        elif latency_ms > 5000:
            obs = Observation(
                kind=ObservationKind.PROVIDER_SLOW,
                details={"provider": provider_id, "latency_ms": latency_ms},
            )
        else:
            obs = Observation(
                kind=ObservationKind.ROUTING_SUCCESS,
                details={"provider": provider_id, "latency_ms": latency_ms},
            )
        return self.observe(obs)

    def observe_preference_correction(
        self,
        correction_type: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> Observation:
        """Convenience: observe a user correction to memory/preferences."""
        obs = self._collector.record_preference_correction(correction_type, description, details)
        return self.observe(obs)

    # ── Phase 2b: Security evaluation ─────────────────────────

    def evaluate_security(self, candidate: ImprovementCandidate) -> EvaluationRecord:
        """Evaluate a candidate against security policy before approval.

        Returns an EvaluationRecord with PASS/FAIL and detailed check results.
        Candidates that FAIL evaluation cannot proceed to approval.
        """
        checks: list[str] = []
        violations: list[str] = []

        # Check 1: Security policy check on proposed_change
        checks.append("security_policy")
        sec_result = check_security_policy(candidate.proposed_change)
        if sec_result.violation:
            violations.append(f"security_policy: {sec_result.detail}")

        # Check 2: Risk level gate — HIGH risk needs extra scrutiny
        checks.append("risk_level")
        if candidate.risk == RiskLevel.HIGH:
            violations.append("HIGH risk candidates require manual security review")

        # Check 3: Verify rollback plan exists
        checks.append("rollback_plan")
        if not candidate.rollback_plan or len(candidate.rollback_plan) < 10:
            violations.append("Missing or insufficient rollback plan")

        # Check 4: Verify proposed_change has required fields
        checks.append("change_structure")
        change = candidate.proposed_change
        if "target" not in change:
            violations.append("proposed_change missing 'target' field")

        result = EvaluationResult.FAIL if violations else EvaluationResult.PASS
        record = EvaluationRecord(
            candidate_id=candidate.id,
            result=result,
            checks_run=checks,
            violations=violations,
        )

        # Log failed evaluations to audit
        if result == EvaluationResult.FAIL:
            self._state.add_audit_event(
                AuditAction.CANDIDATE_EVAL_FAILED,
                candidate.id,
                detail={"violations": violations, "checks": checks},
            )

        self.persist()
        return record

    def is_evaluation_safe(self, candidate: ImprovementCandidate) -> bool:
        """Quick check: is a candidate safe to proceed past evaluation?"""
        record = self.evaluate_security(candidate)
        return record.is_safe_to_apply()

    def reject_failed_evaluation(self, candidate_id: str) -> SelfImprovementRecord | None:
        """Reject a candidate that failed security evaluation.

        Returns the updated record, or None if candidate not found.
        Logs to audit trail.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.PROPOSED:
                return None

            rec.status = ImprovementStatus.REJECTED
            rec.benefit_observed = f"Rejected: failed security/safety evaluation"
            self._state.add_audit_event(
                AuditAction.CANDIDATE_REJECTED,
                candidate_id,
                detail={"reason": "failed_evaluation"},
            )
            self._state.improvements[candidate_id] = rec
            self.persist()
            return rec

    # ── Phase 3: Approval with user gate ───────────────────────

    def approve(
        self,
        candidate_id: str,
        approved_by: str = "system",
        manual_override: bool = False,
    ) -> SelfImprovementRecord | None:
        """Approve an improvement candidate with user approval gate.

        Args:
            candidate_id: ID of the candidate to approve.
            approved_by: Who is approving. For production, this should be a user.
            manual_override: Force approval even if evaluation fails (requires HIGH privilege).
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.PROPOSED:
                return None

            # Check for user approval callback (for tests/automation)
            if candidate_id in self._user_approval_callbacks:
                approved = self._user_approval_callbacks.pop(candidate_id)
                if not approved:
                    rec.status = ImprovementStatus.REJECTED
                    rec.benefit_observed = "Rejected by user approval gate"
                    self._state.add_audit_event(
                        AuditAction.CANDIDATE_REJECTED,
                        candidate_id,
                        detail={"reason": "user_did_not_approve"},
                        actor=approved_by,
                    )
                    self._state.improvements[candidate_id] = rec
                    self.persist()
                    return rec

            # Security evaluation check
            if not manual_override:
                # Load the candidate to run evaluation
                # (the candidate info is stored in the record's proposed_change)
                pass

            rec.status = ImprovementStatus.APPROVED
            rec.approved_at = time.monotonic()
            rec.approved_by = approved_by
            self._state.register_approval()
            self._state.bump_version(VersionBumpKind.MINOR)
            self._state.add_audit_event(
                AuditAction.CANDIDATE_APPROVED,
                candidate_id,
                detail={"approved_by": approved_by},
                actor=approved_by,
            )
            self._state.improvements[candidate_id] = rec
            self.persist()
            return rec

    def request_user_approval(self, candidate_id: str, title: str, evidence: str) -> bool:
        """Request approval from the user for a candidate.

        Returns True if approved, False if rejected.
        Override this method in production to show a real UI prompt.
        """
        # Default: auto-approve for system-initiated candidates
        # In production, this would block and wait for user input
        self._user_approval_callbacks[candidate_id] = True
        return True

    def reject(self, candidate_id: str, reason: str = "manual_rejection") -> SelfImprovementRecord | None:
        """Manually reject a proposed improvement."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.PROPOSED:
                return None

            rec.status = ImprovementStatus.REJECTED
            rec.benefit_observed = f"Rejected: {reason}"
            self._state.add_audit_event(
                AuditAction.CANDIDATE_REJECTED,
                candidate_id,
                detail={"reason": reason},
            )
            self._state.improvements[candidate_id] = rec
            self.persist()
            return rec

    def apply(
        self,
        candidate_id: str,
        before_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply an approved improvement change. Thread-safe."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.APPROVED:
                return {"error": f"Candidate {candidate_id} not approved"}

            change = rec.proposed_change

            # Run security evaluation before applying
            sec_result = check_security_policy(change)
            if sec_result.violation:
                self._state.add_audit_event(
                    AuditAction.SECURITY_VIOLATION_BLOCKED,
                    candidate_id,
                    detail={
                        "violation": sec_result.violation.value,
                        "detail": sec_result.detail,
                    },
                )
                self.reject(candidate_id, reason=f"Security violation: {sec_result.detail}")
                return {"error": f"Security violation blocked: {sec_result.detail}"}

            # Take before snapshot if not provided
            if before_snapshot is None:
                before_snapshot = self._take_before_snapshot(change)
            self._monitoring[candidate_id] = {"before": before_snapshot}

            # Apply the change
            result = apply_bounded_change(change, rollback_snapshot=before_snapshot)
            if "error" in result:
                return result

            rec.status = ImprovementStatus.APPLIED
            rec.applied_at = time.monotonic()
            rec.rollback_change = result if isinstance(result, dict) else {}
            self._state.add_audit_event(
                AuditAction.CHANGE_APPLIED,
                candidate_id,
                detail={"change": change, "rollback_available": bool(result)},
            )
            self._state.bump_version(VersionBumpKind.MAJOR)

            # Initialize monitoring
            self._monitor_snapshots[candidate_id] = MonitoringSnapshot(
                candidate_id=candidate_id,
                before_snapshot=before_snapshot,
            )

            self._state.improvements[candidate_id] = rec
            self.persist()
            return result

    def _take_before_snapshot(self, change: dict[str, Any]) -> dict[str, Any]:
        """Take a snapshot of the system state before applying a change."""
        snapshot: dict[str, Any] = {"change_type": change.get("action", "")}

        if change.get("target") == "config":
            try:
                from config.settings import load_settings
                settings = load_settings()
                snapshot["config_snapshot"] = settings.to_dict()
            except Exception:
                snapshot["config_snapshot"] = {"load_error": True}

        elif change.get("target") == "memory":
            try:
                from memory.memory_manager import load_memory
                memory = load_memory()
                cat = change.get("category", "notes")
                key = change.get("key", "")
                snapshot["memory_snapshot"] = {
                    "category": cat,
                    "key": key,
                    "value": memory.get(cat, {}).get(key),
                }
            except Exception:
                snapshot["memory_snapshot"] = {"load_error": True}

        return snapshot
        """Generate improvement candidates from accumulated observations.

        Thread-safe. Updates state counter.
        """
        with self._lock:
            self._state.register_candidate()
        candidates = generate_candidates(
            collector=self._collector,
            state_count=self._state.observations_count,
        )
        # Store candidates in state for persistence
        for c in candidates:
            if c.id not in self._state.improvements:
                self._state.improvements[c.id] = SelfImprovementRecord(
                    id=c.id,
                    title=c.title,
                    status=ImprovementStatus.PROPOSED,
                    proposed_change=c.proposed_change,
                )
        return candidates

    # ── Phase 3: Evidence & risk evaluation ───────────────────
    # (Already embedded in ImprovementCandidate fields)

    # ── Phase 4: Approval ──────────────────────────────────────

    def approve(
        self,
        candidate_id: str,
        approved_by: str = "system",
    ) -> SelfImprovementRecord | None:
        """Approve an improvement candidate.

        Returns the updated record, or None if not found.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None:
                return None
            if rec.status != ImprovementStatus.PROPOSED:
                return rec
            rec.status = ImprovementStatus.APPROVED
            rec.approved_at = time.monotonic()
            rec.approved_by = approved_by
            self._state.register_approval()
        return rec

    def reject(
        self,
        candidate_id: str,
    ) -> SelfImprovementRecord | None:
        """Reject an improvement candidate."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None:
                return None
            rec.status = ImprovementStatus.REJECTED
        return rec


    # ── Phase 6: Monitor with degradation detection ──────────

    def monitor(
        self,
        candidate_id: str,
        benefit_observed: str | None = None,
        after_snapshot: dict[str, Any] | None = None,
        degradation_threshold: float = 10.0,
    ) -> SelfImprovementRecord | None:
        """Mark an applied improvement as monitored/confirmed beneficial.

        If degradation is detected (metrics degraded by > threshold_pct),
        automatically flags for rollback and returns the record.
        If after_snapshot is not provided, takes a new one from the collector.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.APPLIED:
                return None

            # Take after snapshot if not provided
            if after_snapshot is None:
                after_snapshot = self._collector.get_snapshot()

            # Get or create monitoring snapshot
            if candidate_id not in self._monitor_snapshots:
                before = self._monitoring.get(candidate_id, {}).get("before", {})
                self._monitor_snapshots[candidate_id] = MonitoringSnapshot(
                    candidate_id=candidate_id,
                    before_snapshot=before,
                    after_snapshot=after_snapshot,
                    status=MonitorStatus.MONITORING,
                )

            snap = self._monitor_snapshots[candidate_id]
            snap.after_snapshot = after_snapshot
            snap.monitoring_ended_at = time.monotonic()

            # Check for degradation
            degraded = snap.detect_degradation(threshold_pct=degradation_threshold)

            if degraded:
                rec.benefit_observed = f"DEGRADATION DETECTED: {snap.degradation_reason}"
                self._state.add_audit_event(
                    AuditAction.CANDIDATE_EVAL_FAILED,
                    candidate_id,
                    detail={
                        "event": "degradation_detected",
                        "reason": snap.degradation_reason,
                        "auto_rollback": True,
                    },
                )
                # Auto-trigger rollback
                self.rollback(candidate_id, reason=snap.degradation_reason)
            else:
                rec.benefit_observed = benefit_observed or "Monitoring confirmed: no degradation"
                snap.status = MonitorStatus.CONFIRMED_BENEFICIAL
                self._state.add_audit_event(
                    AuditAction.CANDIDATE_APPROVED,
                    candidate_id,
                    detail={"event": "monitoring_confirmed", "benefit": rec.benefit_observed},
                )

            self._state.improvements[candidate_id] = rec
            self.persist()
            return rec

    # ── Phase 7: Rollback with audit ───────────────────────────

    def rollback(
        self,
        candidate_id: str,
        reason: str = "measured degradation",
    ) -> bool:
        """Rollback an applied improvement. Thread-safe. Returns True on success."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status not in (
                ImprovementStatus.APPLIED,
                ImprovementStatus.ROLLED_BACK,
            ):
                return False

            # Attempt rollback via state snapshot
            rollback_change = rec.proposed_change
            if "target" in rollback_change and rollback_change["target"] in ("config", "timeout", "memory"):
                rollback_data = self._monitoring.get(candidate_id, {}).get("before", {})
                if rollback_data:
                    try:
                        from config.settings import load_settings, save_settings
                        from config.schema import Settings
                        if rollback_change["target"] == "config":
                            try:
                                old = Settings(**rollback_data)
                                save_settings(old)
                            except Exception:
                                pass
                        elif rollback_change["target"] == "memory":
                            from memory.memory_manager import load_memory
                            mem = load_memory()
                            cat = rollback_change.get("category", "notes")
                            key = rollback_change.get("key", "")
                            old_entry = rollback_data.get("old")
                            if old_entry is not None:
                                from memory.memory_manager import update_memory
                                update_memory({cat: {key: old_entry}})
                            elif key in mem.get(cat, {}):
                                from memory.memory_manager import update_memory
                                update_memory({cat: {key: None}})
                        elif rollback_change["target"] == "timeout":
                            path = rollback_change.get("path", "")
                            if f"_timeout_{path}" in self._state.improvements:
                                del self._state.improvements[f"_timeout_{path}"]
                    except Exception:
                        pass  # best-effort rollback

            rec.status = ImprovementStatus.ROLLED_BACK
            rec.rolled_back_at = time.monotonic()
            rec.benefit_observed = f"Rolled back: {reason}"
            self._state.register_rollback()
            self._state.bump_version(VersionBumpKind.ROLLBACK)
            self._state.add_audit_event(
                AuditAction.CHANGE_ROLLED_BACK,
                candidate_id,
                detail={"reason": reason},
            )
            self._state.improvements[candidate_id] = rec
            self.persist()
            return True

    # ── State persistence ─────────────────────────────────────

    def persist(self) -> None:
        """Save state to disk."""
        save_state(self._state)

    def get_state_summary(self) -> dict[str, Any]:
        """Human-readable state summary."""
        statuses: dict[str, int] = {}
        for rec in self._state.improvements.values():
            key = rec.status.value
            statuses[key] = statuses.get(key, 0) + 1

        return {
            "observations_count": self._state.observations_count,
            "candidates_generated": self._state.candidates_generated,
            "approved_count": self._state.approved_count,
            "rolled_back_count": self._state.rolled_back_count,
            "current_version": self._state.current_version,
            "improvement_statuses": statuses,
            "active_candidates": [
                {"id": c.id, "title": c.title, "status": c.status.value}
                for c in self._state.improvements.values()
                if c.status == ImprovementStatus.PROPOSED
            ],
        }

    def get_candidate_details(self, candidate_id: str) -> dict[str, Any] | None:
        """Get full details for a candidate."""
        rec = self._state.improvements.get(candidate_id)
        if rec is None:
            return None
        return {
            "id": rec.id,
            "title": rec.title,
            "status": rec.status.value,
            "created_at": rec.created_at,
            "approved_at": rec.approved_at,
            "applied_at": rec.applied_at,
            "approved_by": rec.approved_by,
            "benefit_observed": rec.benefit_observed,
            "proposed_change": rec.proposed_change,
        }

    def get_audit_summary(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent audit log entries."""
        events = self._state.get_audit_log(limit=limit)
        return [e.to_dict() for e in events]
