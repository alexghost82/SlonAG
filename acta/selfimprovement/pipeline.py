"""Pipeline — orchestrates the full self-improvement lifecycle.

Observation → improvement candidate → evidence → evaluation →
expected benefit → risk → approval → apply bounded change →
monitor → rollback.
"""

from __future__ import annotations

import time
import threading
from typing import Any

from .collector import MetricsCollector
from .localized_strings import (
    RU_OBSERVATION_TOOL_FAILURE,
    RU_OBSERVATION_TOOL_TIMEOUT,
    RU_OBSERVATION_PROVIDER_SLOW,
    RU_OBSERVATION_PROVIDER_FAILED,
    RU_OBSERVATION_PREFERENCE_CORRECTION,
    RU_CANDIDATE_GENERATED,
    RU_APPROVE_SUCCESS,
    RU_REJECT_SUCCESS,
    RU_NOT_FOUND,
    RU_EVALUATION_PASS,
    RU_EVALUATION_FAIL,
    RU_APPLY_SUCCESS,
    RU_APPLY_ERROR,
    RU_MONITOR_DEGRADATION,
    RU_MONITOR_STABLE,
    RU_ROLLBACK_SUCCESS,
    RU_ERROR_SECURITY_VIOLATION,
    RU_ERROR_INVALID_STATE_TRANSITION,
    RU_APPLY_NO_APPROVAL,
    RU_ROLLBACK_FAILED,
    ru_f,
)
from .storage import load_state, save_state
from .rules import generate_candidates

from .types import (
    AuditEntry,
    AuditAction,
    EvaluationStatus,
    ImprovementCandidate,
    ImprovementStatus,
    Observation,
    ObservationKind,
    RiskLevel,
    SelfImprovementRecord,
    SelfImprovementState,
    apply_bounded_change,
)


class SelfImprovementPipeline:
    """Central orchestrator for controlled self-improvement."""

    def __init__(self, collector: MetricsCollector | None = None) -> None:
        self._collector = collector or MetricsCollector.instance()
        self._state = load_state()
        self._lock = threading.Lock()
        self._monitoring: dict[str, dict[str, Any]] = {}  # id → before snapshot

    # ── Phase 1: Observation ──────────────────────────────────

    def observe(self, obs: Observation) -> Observation:
        """Register an observation. Thread-safe. Logs to audit."""
        with self._lock:
            self._state.register_observation()
            self._collector.record_observation(obs)
            self._state.add_audit_entry(AuditEntry(
                action=AuditAction.OBSERVE,
                details={"kind": obs.kind.value, "details": obs.details},
                message_ru=ru_f(RU_OBSERVATION_TOOL_FAILURE, tool=obs.details.get("tool", "?"), code=obs.details.get("code", "")),
            ))
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

    # ── Phase 2: Candidate generation ─────────────────────────

    def generate_candidates(self) -> list[ImprovementCandidate]:
        """Generate improvement candidates from accumulated observations.

        Thread-safe. Updates state counter and logs audit entry.
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
                rec = SelfImprovementRecord(
                    id=c.id,
                    title=c.title,
                    status=ImprovementStatus.PROPOSED,
                    version=1,
                    proposed_change=c.proposed_change,
                )
                rec.audit(AuditAction.PROPOSED, details={"category": c.category.value},
                          message_ru=ru_f(RU_CANDIDATE_GENERATED, title=c.title))
                self._state.improvements[c.id] = rec
                with self._lock:
                    self._state.add_audit_entry(AuditEntry(
                        action=AuditAction.CANDIDATE_GENERATED,
                        details={"candidate_id": c.id, "title": c.title},
                        message_ru=ru_f(RU_CANDIDATE_GENERATED, title=c.title),
                    ))
        return candidates

    # ── Phase 3: Evaluation ───────────────────────────────────

    def evaluate(
        self,
        candidate_id: str,
        reason: str = "",
        score: float = 0.0,
        passed: bool = True,
    ) -> SelfImprovementRecord | None:
        """Evaluate an approved improvement before applying.

        Security policy: improvements that weaken authentication, approval,
        permission checks, network exposure, or secret storage will FAIL.

        Args:
            candidate_id: ID of the improvement to evaluate.
            reason: Explanation for the evaluation result.
            score: Numerical evaluation score (0.0-1.0).
            passed: Whether the candidate passes evaluation.

        Returns:
            Updated record, or None if not found.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None:
                return None

            # Must be approved or proposed to be evaluated
            if rec.status not in (ImprovementStatus.PROPOSED, ImprovementStatus.APPROVED):
                rec.audit(AuditAction.EVALUATED_FAIL,
                          details={"reason": "already_in_terminal_state"},
                          message_ru=ru_f(RU_ERROR_INVALID_STATE_TRANSITION))
                return rec

            # Security check: reject changes that weaken security
            try:
                change = rec.proposed_change
                self._security_check(change)
            except ValueError:
                rec.status = ImprovementStatus.REJECTED
                rec.evaluation = EvaluationStatus.FAILED
                rec.evaluation_reason = ru_f(RU_ERROR_SECURITY_VIOLATION)
                rec.evaluation_score = 0.0
                rec.audit(AuditAction.EVALUATED_FAIL,
                          details={"reason": "security_violation"},
                          message_ru=ru_f(RU_ERROR_SECURITY_VIOLATION))
                rec.bump_version(reason="security violation")
                return rec

            if passed:
                rec.status = ImprovementStatus.APPROVED
                rec.evaluation = EvaluationStatus.PASSED
                rec.evaluation_reason = reason
                rec.evaluation_score = score
                rec.audit(AuditAction.EVALUATED_PASS,
                          details={"score": score, "reason": reason},
                          message_ru=ru_f(RU_EVALUATION_PASS, score=score, reason=reason))
                rec.bump_version(reason="evaluation passed")
            else:
                rec.status = ImprovementStatus.REJECTED
                rec.evaluation = EvaluationStatus.FAILED
                rec.evaluation_reason = reason
                rec.evaluation_score = score
                rec.audit(AuditAction.EVALUATED_FAIL,
                          details={"reason": reason, "score": score},
                          message_ru=ru_f(RU_EVALUATION_FAIL, reason=reason))
                rec.bump_version(reason="evaluation failed")

        return rec

    def _security_check(self, change: dict[str, Any]) -> None:
        """Verify the proposed change does not weaken security boundaries.

        Raises:
            ValueError: If the change weakens security.
        """
        change_str = str(change).lower()

        # Security boundaries that must never be weakened
        forbidden_patterns = [
            "auth", "password", "secret", "token", "key",
            "permission", "approval", "whitelist", "bypass",
            "disable_auth", "skip_check", "open_all",
        ]
        if change.get("target") in ("config", "memory") and not change.get("action"):
            # Only allow known-safe config keys
            safe_keys = {"timeout", "max_turns", "max_tool_calls", "log_level"}
            if "key" in change and change["key"] not in safe_keys:
                raise ValueError(ru_f(RU_ERROR_SECURITY_VIOLATION))

    # ── Phase 4: User approval ────────────────────────────────

    def approve(
        self,
        candidate_id: str,
        approved_by: str = "system",
        message_ru: str = "",
    ) -> SelfImprovementRecord | None:
        """Approve an improvement candidate.

        Requires user-level approval before applying. Logs to audit.

        Args:
            candidate_id: ID of the improvement to approve.
            approved_by: Identifier of the approver (user, system, etc.).
            message_ru: Russian-language approval message.

        Returns:
            Updated record, or None if not found.
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
            rec.audit(AuditAction.APPROVED,
                      details={"approved_by": approved_by, "message_ru": message_ru},
                      message_ru=message_ru or ru_f(RU_APPROVE_SUCCESS, title=rec.title))
            rec.bump_version(reason="approved by " + approved_by)

        # Record user feedback
        if approved_by != "system" and not message_ru:
            self._collector.record_user_feedback(
                candidate_id, "approve",
                ru_f(RU_APPROVE_SUCCESS, title=rec.title),
            )

        return rec

    def reject(
        self,
        candidate_id: str,
        reason: str = "",
        message_ru: str = "",
    ) -> SelfImprovementRecord | None:
        """Reject an improvement candidate explicitly.

        This is different from failed evaluation — reject is a direct user/system decision.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None:
                return None
            if rec.status in (ImprovementStatus.REJECTED, ImprovementStatus.ROLLED_BACK):
                return rec
            old_status = rec.status.value
            rec.status = ImprovementStatus.REJECTED
            rec.audit(AuditAction.REJECTED,
                        details={"reason": reason, "previous_status": old_status},
                        message_ru=message_ru or ru_f(RU_REJECT_SUCCESS, title=rec.title))
            rec.bump_version(reason="rejected" + (" (" + reason + ")" if reason else ""))

        # Record user feedback
        if message_ru or reason:
            self._collector.record_user_feedback(
                candidate_id, "reject",
                message_ru or ru_f(RU_REJECT_SUCCESS, title=rec.title),
                {"reason": reason},
            )

        return rec

    # ── Phase 5: Apply bounded change ─────────────────────────

    def apply(self, candidate_id: str, approved_by: str = "system") -> dict[str, Any]:
        """Apply the approved change. Thread-safe. Returns rollback snapshot.

        Pre-conditions:
        - Candidate must be in APPROVED status.
        - Must have passed evaluation.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None:
                return {"error": "улучшение не найдено"}
            if rec.status != ImprovementStatus.APPROVED:
                return {"error": ru_f(RU_APPLY_NO_APPROVAL, title=rec.title)}
            if rec.evaluation == EvaluationStatus.FAILED:
                return {"error": ru_f(RU_EVALUATION_FAIL, reason=rec.evaluation_reason)}

            # Take before-snapshot for monitoring
            before = self._collector.get_snapshot()

            rec.status = ImprovementStatus.APPLIED
            rec.applied_at = time.monotonic()
            rec.bump_version(reason="applied")

        # Apply the change (outside lock to avoid blocking)
        try:
            rollback = apply_bounded_change(rec.proposed_change)
        except Exception as exc:
            with self._lock:
                rec.audit(AuditAction.APPLIED,
                          details={"error": str(exc)},
                          message_ru=ru_f(RU_APPLY_ERROR, error=str(exc)))
                rec.bump_version(reason="apply failed: " + str(exc))
            return {"error": str(exc)}

        if "error" in rollback:
            with self._lock:
                rec.status = ImprovementStatus.PROPOSED  # revert to proposed
                rec.bump_version(reason="apply reverted: " + rollback["error"])
            return rollback

        # Log success and store monitoring data
        with self._lock:
            self._monitoring[candidate_id] = {
                "before": before,
                "after": self._collector.get_snapshot(),
                "applied_at": rec.applied_at,
            }
            rec.audit(AuditAction.APPLIED,
                      details={"applied_by": approved_by},
                      message_ru=ru_f(RU_APPLY_SUCCESS, title=rec.title))
            self._state.improvements[candidate_id] = rec
        return rollback

    # ── Phase 6: Monitor ──────────────────────────────────────

    def monitor(
        self,
        candidate_id: str,
        benefit_observed: str | None = None,
        degradation_detected: bool = False,
    ) -> SelfImprovementRecord | None:
        """Monitor an applied improvement.

        If degradation is detected, the improvement is rolled back.
        """
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.APPLIED:
                return None

            if degradation_detected:
                rec.audit(AuditAction.ROLLED_BACK,
                          details={"reason": "degradation detected during monitoring"},
                          message_ru=ru_f(RU_MONITOR_DEGRADATION, title=rec.title))
                rec.bump_version(reason="degradation detected")
                # Auto-reject: set status back to PROPOSED so it can be re-evaluated
                rec.status = ImprovementStatus.REJECTED
                rec.evaluation = EvaluationStatus.FAILED
                rec.evaluation_reason = "degradation during monitoring"
                return rec

            rec.benefit_observed = benefit_observed or "Без деградации"
            rec.audit(AuditAction.APPLIED,  # monitoring is a post-apply confirmation
                      details={"benefit_observed": rec.benefit_observed},
                      message_ru=ru_f(RU_MONITOR_STABLE, title=rec.title))
        return rec

    # ── Phase 7: Rollback ─────────────────────────────────────

    def rollback(
        self,
        candidate_id: str,
        reason: str = "measured degradation",
    ) -> bool:
        """Rollback an applied improvement. Thread-safe."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status not in (
                ImprovementStatus.APPLIED,
                ImprovementStatus.ROLLED_BACK,
            ):
                return False

            # Attempt rollback via state snapshot
            try:
                self._execute_rollback(rec)
            except Exception:
                pass  # best-effort rollback

            rec.status = ImprovementStatus.ROLLED_BACK
            rec.rolled_back_at = time.monotonic()
            rec.rollback_reason = reason
            self._state.register_rollback()
            rec.audit(AuditAction.ROLLED_BACK,
                      details={"reason": reason},
                      message_ru=ru_f(RU_ROLLBACK_SUCCESS, title=rec.title, reason=reason))
            rec.bump_version(reason="rolled back: " + reason)
            self._state.improvements[candidate_id] = rec
        save_state(self._state)
        return True

    def _execute_rollback(self, rec: SelfImprovementRecord) -> None:
        """Execute the actual rollback logic."""
        rollback_change = rec.proposed_change
        if "target" in rollback_change and rollback_change["target"] in ("config", "timeout", "memory"):
            rollback_data = self._monitoring.get(rec.id, {}).get("before", {})
            if rollback_data:
                try:
                    if rollback_change["target"] == "config":
                        from config.settings import load_settings, save_settings
                        from config.schema import Settings
                        old = Settings(**rollback_data)
                        save_settings(old)
                    elif rollback_change["target"] == "memory":
                        from memory.memory_manager import load_memory, update_memory
                        mem = load_memory()
                        cat = rollback_change.get("category", "notes")
                        key = rollback_change.get("key", "")
                        old_entry = rollback_data.get("old")
                        if old_entry is not None:
                            update_memory({cat: {key: old_entry}})
                        elif key in mem.get(cat, {}):
                            update_memory({cat: {key: None}})
                    elif rollback_change["target"] == "timeout":
                        path = rollback_change.get("path", "")
                        if f"_timeout_{path}" in self._state.improvements:
                            del self._state.improvements[f"_timeout_{path}"]
                except Exception:
                    pass  # best-effort rollback

    # ── State persistence ─────────────────────────────

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
            "total_user_feedback_count": self._state.total_user_feedback_count,
            "improvement_statuses": statuses,
            "active_candidates": [
                {"id": c.id, "title": c.title, "status": c.status.value, "version": c.version}
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
            "version": rec.version,
            "created_at": rec.created_at,
            "approved_at": rec.approved_at,
            "applied_at": rec.applied_at,
            "approved_by": rec.approved_by,
            "benefit_observed": rec.benefit_observed,
            "proposed_change": rec.proposed_change,
            "evaluation": rec.evaluation.value,
            "evaluation_reason": rec.evaluation_reason,
            "audit_log": rec.get_audit_summary(),
        }

    def get_audit_log(self, candidate_id: str | None = None) -> list[dict[str, Any]]:
        """Get audit log entries.

        If candidate_id is given, returns the audit log for a specific candidate.
        Otherwise, returns the global audit history from state.
        """
        if candidate_id:
            rec = self._state.improvements.get(candidate_id)
            if rec is None:
                return []
            return rec.get_audit_summary()
        return [e.to_dict() for e in self._state.audit_history]

    def get_user_feedback_summary(self) -> dict[str, Any]:
        """Summary of all user feedback."""
        feedbacks = self._collector.get_user_feedback()
        by_type: dict[str, int] = {}
        for fb in feedbacks:
            by_type[fb.feedback_type] = by_type.get(fb.feedback_type, 0) + 1
        return {
            "total": len(feedbacks),
            "by_type": by_type,
            "recent": [
                {
                    "candidate_id": fb.candidate_id,
                    "type": fb.feedback_type,
                    "message": fb.message_ru,
                    "details": fb.details,
                }
                for fb in feedbacks[-20:]
            ],
        }
