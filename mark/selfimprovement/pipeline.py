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

    # ── Phase 2: Candidate generation ─────────────────────────

    def generate_candidates(self) -> list[ImprovementCandidate]:
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

    # ── Phase 5: Apply bounded change ─────────────────────────

    def apply(self, candidate_id: str, approved_by: str = "system") -> dict[str, Any]:
        """Apply the approved change. Thread-safe. Returns rollback snapshot."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.APPROVED:
                return {"error": "candidate not approved"}

            # Take before-snapshot for monitoring
            before = self._collector.get_snapshot()

            rec.status = ImprovementStatus.APPLIED
            rec.applied_at = time.monotonic()
            self._state.improvements[candidate_id] = rec

        # Apply the change (outside lock to avoid blocking)
        rollback = apply_bounded_change(rec.proposed_change)

        if "error" in rollback:
            with self._lock:
                rec.status = ImprovementStatus.PROPOSED  # revert to proposed
            return rollback

        # Store monitoring data
        with self._lock:
            self._monitoring[candidate_id] = {
                "before": before,
                "after": self._collector.get_snapshot(),
                "applied_at": rec.applied_at,
            }
            self._state.improvements[candidate_id] = rec
        return rollback

    # ── Phase 6: Monitor ──────────────────────────────────────

    def monitor(
        self,
        candidate_id: str,
        benefit_observed: str | None = None,
    ) -> SelfImprovementRecord | None:
        """Mark an applied improvement as monitored/confirmed beneficial."""
        with self._lock:
            rec = self._state.improvements.get(candidate_id)
            if rec is None or rec.status != ImprovementStatus.APPLIED:
                return None
            rec.benefit_observed = benefit_observed
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
                            # Remove the timeout override
                            path = rollback_change.get("path", "")
                            if f"_timeout_{path}" in self._state.improvements:
                                del self._state.improvements[f"_timeout_{path}"]
                    except Exception:
                        pass  # best-effort rollback

            rec.status = ImprovementStatus.ROLLED_BACK
            rec.rolled_back_at = time.monotonic()
            rec.rollback_reason = reason
            self._state.register_rollback()
            self._state.improvements[candidate_id] = rec
        save_state(self._state)
        return True

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
            "improvement_statuses": statuses,
            "active_candidates": [
                {"id": c.id, "title": c.title, "category": c.category.value, "risk": c.risk.value}
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
