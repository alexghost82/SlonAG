"""MetricsCollector — gathers runtime statistics for self-improvement."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .types import Observation, ObservationKind


@dataclass
class ToolMetric:
    """Per-tool accumulated metrics."""
    tool_name: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_latency_ms: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    failure_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class ProviderMetric:
    """Per-provider accumulated metrics."""
    provider_id: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    total_latency_ms: float = 0.0
    routing_decisions: int = 0


@dataclass
class WorkflowMetric:
    """Per-session workflow statistics."""
    session_id: str
    tool_calls: int = 0
    turns: int = 0
    loop_detections: int = 0
    redundant_calls: int = 0


@dataclass
class UserFeedback:
    """A user's explicit feedback on an improvement."""
    candidate_id: str
    feedback_type: str  # "approve" | "reject" | "feedback"
    message_ru: str
    timestamp: float = field(default_factory=time.monotonic)
    details: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Thread-safe singleton for collecting self-improvement metrics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tool_metrics: dict[str, ToolMetric] = {}
        self._provider_metrics: dict[str, ProviderMetric] = {}
        self._workflow_metrics: dict[str, WorkflowMetric] = {}
        self._observations: list[Observation] = []  # ring buffer
        self._max_observations = 500
        self._preference_corrections: list[dict[str, Any]] = []
        self._user_feedback: list[UserFeedback] = []

    @classmethod
    def instance(cls) -> MetricsCollector:
        import acta.selfimprovement
        return acta.selfimprovement.get_collector()

    # ── Tool metrics ──────────────────────────────────────────

    def record_tool_call(
        self,
        tool_name: str,
        latency_ms: float,
        success: bool,
        code: str = "ok",
        timeout: bool = False,
    ) -> None:
        with self._lock:
            if tool_name not in self._tool_metrics:
                self._tool_metrics[tool_name] = ToolMetric(tool_name=tool_name)
            m = self._tool_metrics[tool_name]
            m.call_count += 1
            m.total_latency_ms += latency_ms
            if timeout:
                m.timeout_count += 1
                m.failure_count += 1
                m.last_failure_at = time.monotonic()
                m.failure_reasons["timeout"] = m.failure_reasons.get("timeout", 0) + 1
            elif success:
                m.success_count += 1
                m.last_success_at = time.monotonic()
            else:
                m.failure_count += 1
                m.last_failure_at = time.monotonic()
                m.failure_reasons[code] = m.failure_reasons.get(code, 0) + 1

    def record_tool_failure(self, tool_name: str, code: str) -> Observation:
        obs = Observation(
            kind=ObservationKind.TOOL_FAILURE,
            details={"tool": tool_name, "code": code},
            metric_ref=tool_name,
        )
        self._observations.append(obs)
        return obs

    def record_tool_timeout(self, tool_name: str, timeout_seconds: float) -> Observation:
        obs = Observation(
            kind=ObservationKind.TOOL_TIMEOUT,
            details={"tool": tool_name, "timeout_seconds": timeout_seconds},
            metric_ref=tool_name,
        )
        self._observations.append(obs)
        return obs

    def get_tool_stats(self, tool_name: str) -> dict[str, Any] | None:
        with self._lock:
            m = self._tool_metrics.get(tool_name)
            if m is None:
                return None
            return {
                "tool": tool_name,
                "calls": m.call_count,
                "success_rate": round(m.success_count / m.call_count, 3) if m.call_count else 0.0,
                "avg_latency_ms": round(m.total_latency_ms / m.call_count, 1) if m.call_count else 0.0,
                "failure_rate": round(m.failure_count / m.call_count, 3) if m.call_count else 0.0,
                "timeout_count": m.timeout_count,
                "failure_reasons": dict(m.failure_reasons),
                "last_success_age_s": round(time.monotonic() - m.last_success_at, 0) if m.last_success_at else None,
            }

    def all_tool_stats(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: self._get_tool_stats_raw(m) for name, m in self._tool_metrics.items()}

    def _get_tool_stats_raw(self, m: ToolMetric) -> dict[str, Any]:
        return {
            "calls": m.call_count,
            "success_rate": round(m.success_count / m.call_count, 3) if m.call_count else 0.0,
            "avg_latency_ms": round(m.total_latency_ms / m.call_count, 1) if m.call_count else 0.0,
            "failure_rate": round(m.failure_count / m.call_count, 3) if m.call_count else 0.0,
            "timeout_count": m.timeout_count,
            "failure_reasons": dict(m.failure_reasons),
        }

    # ── Provider metrics ──────────────────────────────────────

    def record_provider_call(
        self,
        provider_id: str,
        latency_ms: float,
        success: bool,
        timeout: bool = False,
        routing_decision: bool = False,
    ) -> None:
        with self._lock:
            if provider_id not in self._provider_metrics:
                self._provider_metrics[provider_id] = ProviderMetric(provider_id=provider_id)
            m = self._provider_metrics[provider_id]
            m.call_count += 1
            m.total_latency_ms += latency_ms
            if routing_decision:
                m.routing_decisions += 1
            if timeout:
                m.timeout_count += 1
                m.failure_count += 1
            elif success:
                m.success_count += 1
            else:
                m.failure_count += 1

    def get_provider_stats(self, provider_id: str) -> dict[str, Any] | None:
        with self._lock:
            m = self._provider_metrics.get(provider_id)
            if m is None:
                return None
            return {
                "provider": provider_id,
                "calls": m.call_count,
                "success_rate": round(m.success_count / m.call_count, 3) if m.call_count else 0.0,
                "avg_latency_ms": round(m.total_latency_ms / m.call_count, 1) if m.call_count else 0.0,
                "failure_rate": round(m.failure_count / m.call_count, 3) if m.call_count else 0.0,
                "timeout_count": m.timeout_count,
                "routing_decisions": m.routing_decisions,
            }

    def all_provider_stats(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {pid: self._get_provider_stats_raw(m) for pid, m in self._provider_metrics.items()}

    def _get_provider_stats_raw(self, m: ProviderMetric) -> dict[str, Any]:
        return {
            "calls": m.call_count,
            "success_rate": round(m.success_count / m.call_count, 3) if m.call_count else 0.0,
            "avg_latency_ms": round(m.total_latency_ms / m.call_count, 1) if m.call_count else 0.0,
            "failure_rate": round(m.failure_count / m.call_count, 3) if m.call_count else 0.0,
            "timeout_count": m.timeout_count,
            "routing_decisions": m.routing_decisions,
        }

    # ── Workflow metrics ──────────────────────────────────────

    def record_workflow_event(
        self,
        session_id: str,
        event: str,
        count: int = 1,
    ) -> None:
        with self._lock:
            if session_id not in self._workflow_metrics:
                self._workflow_metrics[session_id] = WorkflowMetric(session_id=session_id)
            m = self._workflow_metrics[session_id]
            if event == "tool_call":
                m.tool_calls += count
            elif event == "turn":
                m.turns += count
            elif event == "loop_detection":
                m.loop_detections += count
            elif event == "redundant_call":
                m.redundant_calls += count

    # ── Preference corrections ────────────────────────────────

    def record_preference_correction(
        self,
        correction_type: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> Observation:
        obs = Observation(
            kind=ObservationKind.PREFERENCE_CORRECTION,
            details={
                "correction_type": correction_type,
                "description": description,
                **(details or {}),
            },
        )
        self._observations.append(obs)
        self._preference_corrections.append({
            "type": correction_type,
            "description": description,
            "details": details,
            "at": time.monotonic(),
        })
        return obs

    # ── User feedback ─────────────────────────────────────────

    def record_user_feedback(
        self,
        candidate_id: str,
        feedback_type: str,
        message_ru: str,
        details: dict[str, Any] | None = None,
    ) -> UserFeedback:
        """Record explicit user feedback on an improvement.

        Args:
            candidate_id: ID of the improvement candidate.
            feedback_type: "approve", "reject", or "feedback".
            message_ru: Russian-language user message.
            details: Optional additional data.
        """
        fb = UserFeedback(
            candidate_id=candidate_id,
            feedback_type=feedback_type,
            message_ru=message_ru,
            details=details or {},
        )
        with self._lock:
            self._user_feedback.append(fb)
        return fb

    def get_user_feedback(self, candidate_id: str | None = None) -> list[UserFeedback]:
        """Get user feedback, optionally filtered by candidate."""
        with self._lock:
            if candidate_id:
                return [f for f in self._user_feedback if f.candidate_id == candidate_id]
            return list(self._user_feedback)

    # ── Observations ──────────────────────────────────────────

    def record_observation(self, obs: Observation) -> None:
        with self._lock:
            self._observations.append(obs)
            if len(self._observations) > self._max_observations:
                self._observations = self._observations[-self._max_observations:]

    def recent_observations(
        self,
        kind: ObservationKind | None = None,
        limit: int = 50,
    ) -> list[Observation]:
        with self._lock:
            obs = self._observations[-limit:]
            if kind:
                obs = [o for o in obs if o.kind == kind]
            return list(obs)

    def observation_summary(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for obs in self._observations:
                key = obs.kind.name
                counts[key] = counts.get(key, 0) + 1
            return counts

    # ── Snapshot ──────────────────────────────────────────────

    def get_snapshot(self) -> dict[str, Any]:
        """Full metrics snapshot for analysis."""
        with self._lock:
            return {
                "tool_stats": {name: self._get_tool_stats_raw(m) for name, m in self._tool_metrics.items()},
                "provider_stats": {pid: self._get_provider_stats_raw(m) for pid, m in self._provider_metrics.items()},
                "observation_summary": self.observation_summary(),
                "preference_corrections_count": len(self._preference_corrections),
                "recent_corrections": list(self._preference_corrections[-20:]),
                "user_feedback_count": len(self._user_feedback),
                "recent_user_feedback": [
                    {"candidate_id": f.candidate_id, "type": f.feedback_type, "message": f.message_ru}
                    for f in self._user_feedback[-20:]
                ],
            }
