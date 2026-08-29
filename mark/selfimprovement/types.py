"""Immutable data types for the controlled self-improvement pipeline."""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any


# ── Observations ──────────────────────────────────────────────

class ObservationKind(Enum):
    TOOL_FAILURE = auto()
    TOOL_TIMEOUT = auto()
    PROVIDER_SLOW = auto()
    PROVIDER_FAILED = auto()
    ROUTING_SUBOPTIMAL = auto()
    MEMORY_STALE = auto()
    MEMORY_CONTRADICTION = auto()
    PREFERENCE_CORRECTION = auto()
    WORKFLOW_REDUNDANT = auto()
    CONFIG_UNUSED = auto()
    ROUTING_SUCCESS = auto()
    TOOL_SUCCESS = auto()


class RiskLevel(Enum):
    SAFE = "safe"           # cosmetic, read-only changes
    LOW = "low"             # bounded config changes
    MEDIUM = "medium"       # affects routing or memory
    HIGH = "high"           # structural changes


class EvidenceType(Enum):
    STATISTICAL = "statistical"       # from metrics collection
    PATTERN = "pattern"               # repeated pattern detected
    USER_FEEDBACK = "user_feedback"   # explicit user correction
    BENCHMARK = "benchmark"           # measured performance delta


class MetricKind(Enum):
    TOOL_LATENCY_MS = "tool_latency_ms"
    TOOL_FAILURE_COUNT = "tool_failure_count"
    TOOL_SUCCESS_RATE = "tool_success_rate"
    PROVIDER_LATENCY_MS = "provider_latency_ms"
    PROVIDER_FAILURE_COUNT = "provider_failure_count"
    PROVIDER_SUCCESS_RATE = "provider_success_rate"
    ROUTING_DECISIONS = "routing_decisions"
    ROUTING_SUCCESS_RATE = "routing_success_rate"
    MEMORY_STALE_COUNT = "memory_stale_count"
    MEMORY_CONTRADICTION_COUNT = "memory_contradiction_count"
    WORKFLOW_LOOP_COUNT = "workflow_loop_count"
    PREFERENCE_CORRECTION_COUNT = "preference_correction_count"
    CONFIG_UNUSED_COUNT = "config_unused_count"


@dataclass(frozen=True)
class MetricSnapshot:
    """A point-in-time metric reading."""
    kind: MetricKind
    value: float
    unit: str
    dimensions: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)
    window_seconds: float = 3600.0  # default 1-hour sliding window


@dataclass(frozen=True)
class MetricBucket:
    """Accumulated statistics for a metric dimension."""
    kind: MetricKind
    dimension_key: str
    dimension_value: str
    count: int = 0
    sum_value: float = 0.0
    failure_count: int = 0
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def mean(self) -> float:
        return self.sum_value / self.count if self.count else 0.0

    @property
    def success_rate(self) -> float:
        return 1.0 - (self.failure_count / self.count) if self.count else 0.0


@dataclass(frozen=True)
class Observation:
    """A single observation event."""
    kind: ObservationKind
    timestamp: float = field(default_factory=time.monotonic)
    details: dict[str, Any] = field(default_factory=dict)
    metric_ref: str | None = None  # references a MetricBucket


# ── Improvement Candidates ────────────────────────────────────

class ImprovementCategory(Enum):
    PREFERENCE_REFINEMENT = "preference_refinement"
    MEMORY_QUALITY = "memory_quality"
    WORKFLOW_OPTIMIZATION = "workflow_optimization"
    ROUTING_STATISTICS = "routing_statistics"
    PROVIDER_PERFORMANCE = "provider_performance"
    TOOL_STATS = "tool_success_failure"
    CONFIG_RECOMMENDATION = "configuration_recommendation"
    PROMPT_RECOMMENDATION = "prompt_recommendation"


@dataclass(frozen=True)
class ImprovementCandidate:
    """A proposed improvement, awaiting evaluation and approval."""
    id: str
    category: ImprovementCategory
    title: str
    description: str
    evidence: str
    evidence_type: EvidenceType
    expected_benefit: str
    risk: RiskLevel
    proposed_change: dict[str, Any]
    rollback_plan: str
    created_at: float = field(default_factory=time.monotonic)

    @property
    def key(self) -> str:
        return self.id


# ── Improvement Record ────────────────────────────────────────

class ImprovementStatus(Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


@dataclass
class SelfImprovementRecord:
    """Lifecycle record for one improvement."""
    id: str
    title: str
    status: ImprovementStatus = ImprovementStatus.PROPOSED
    created_at: float = field(default_factory=time.monotonic)
    approved_at: float | None = None
    applied_at: float | None = None
    rolled_back_at: float | None = None
    approved_by: str = "system"
    benefit_observed: str | None = None
    rollback_reason: str | None = None
    proposed_change: dict[str, Any] = field(default_factory=dict)
    rollback_change: dict[str, Any] = field(default_factory=dict)

    def _to_dict(self) -> dict[str, Any]:
        import dataclasses
        if dataclasses.is_dataclass(self):
            result = {}
            for f in dataclasses.fields(self):
                val = getattr(self, f.name)
                if isinstance(val, Enum):
                    val = val.value
                result[f.name] = val
            return result
        return self.__dict__

    @staticmethod
    def _record_from_dict(d: dict[str, Any]) -> "SelfImprovementRecord":
        import dataclasses
        if dataclasses.is_dataclass(SelfImprovementRecord):
            # Convert enum values back
            for k, v in list(d.items()):
                if k in ("status",) and isinstance(v, str):
                    try:
                        d[k] = ImprovementStatus(v)
                    except ValueError:
                        pass
            return SelfImprovementRecord(**d)
        return SelfImprovementRecord(**d)


# ── State ─────────────────────────────────────────────────────

@dataclass
class SelfImprovementState:
    """Persistent state for the self-improvement system with versioning and audit log."""
    observations_count: int = 0
    candidates_generated: int = 0
    approved_count: int = 0
    rolled_back_count: int = 0
    improvements: dict[str, SelfImprovementRecord] = field(default_factory=dict)
    current_version: str = "0.0.0"
    audit_log: list[dict[str, Any]] = field(default_factory=list)  # persisted as dicts

    def register_observation(self) -> None:
        self.observations_count += 1

    def register_candidate(self) -> None:
        self.candidates_generated += 1

    def register_approval(self) -> None:
        self.approved_count += 1

    def register_rollback(self) -> None:
        self.rolled_back_count += 1

    def bump_version(self, bump: VersionBumpKind) -> str:
        """Increment version and log to audit trail. Returns new version string."""
        old = self.current_version
        self.current_version = VersionInfo.next_version(old, bump)
        self._add_audit_event(
            action=AuditAction.CANDIDATE_GENERATED,
            detail={"version_from": old, "version_to": self.current_version, "bump": bump.value},
        )
        return self.current_version

    def add_audit_event(
        self,
        action: AuditAction,
        target_id: str,
        detail: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> AuditEvent:
        """Append an immutable audit event. Returns the event."""
        seq = len(self.audit_log) + 1
        event = AuditEvent(
            sequence=seq,
            action=action,
            target_id=target_id,
            detail=detail or {},
            actor=actor,
        )
        self.audit_log.append(event.to_dict())
        return event

    def get_audit_log(self, action: AuditAction | None = None, limit: int = 100) -> list[AuditEvent]:
        """Return recent audit events, optionally filtered by action."""
        events: list[AuditEvent] = [AuditEvent.from_dict(d) for d in self.audit_log]
        if action:
            events = [e for e in events if e.action == action]
        return events[-limit:]

    def is_audit_immutable(self) -> bool:
        """Verify that audit log is append-only (no deletions or modifications)."""
        for i, d in enumerate(self.audit_log):
            if d.get("sequence") != i + 1:
                return False
        return True


# ── Bounded change application ────────────────────────────────

def apply_bounded_change(
    change: dict[str, Any],
    rollback_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a bounded, reversible change and return the rollback snapshot.

    Currently supports:
    - Writing to a JSON settings file (change key, rollback old value).
    - Adding entries to a memory category.
    - Adjusting a timeout value.
    - Recording a routing statistic.

    Returns the rollback snapshot (previous state).
    """
    rollback: dict[str, Any] = {}
    target = change.get("target")
    action = change.get("action", "set")

    if target == "config":
        from config.settings import load_settings, save_settings
        from config.schema import Settings, SettingsValidationError
        try:
            settings = load_settings()
            rollback_data = settings.to_dict()
            key = change["key"]
            value = change["value"]
            setattr(settings, key, value)
            save_settings(settings)
            rollback = {"type": "config", "rollback_data": rollback_data}
        except (AttributeError, SettingsValidationError) as exc:
            return {"error": f"config change failed: {exc}"}

    elif target == "memory":
        from memory.memory_manager import update_memory
        category = change.get("category", "notes")
        key = change["key"]
        value = change["value"]
        # Snapshot existing
        from memory.memory_manager import load_memory
        memory = load_memory()
        old_entry = memory.get(category, {}).get(key)
        rollback = {"type": "memory", "category": category, "key": key, "old": old_entry}
        update_memory({category: {key: {"value": value, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}}})

    elif target == "timeout":
        # Adjust timeout in a known config path
        timeout_path = change.get("path", "")
        new_timeout = change["value"]
        # Snapshot: store in self-improvement state
        from mark.selfimprovement import load_state
        state = load_state()
        existing = state.improvements.get("_timeout_overrides", SelfImprovementRecord(
            id="_timeout_overrides", title="Timeout overrides"
        ))
        rollback = {"type": "timeout", "path": timeout_path, "old_value": change.get("previous")}
        # Store override in improvement state
        state.improvements[f"_timeout_{timeout_path}"] = SelfImprovementRecord(
            id=f"_timeout_{timeout_path}",
            title=f"Timeout override: {timeout_path}",
            status=ImprovementStatus.APPLIED,
            applied_at=time.monotonic(),
            proposed_change={"path": timeout_path, "value": new_timeout},
            rollback_change=rollback,
        )
        from mark.selfimprovement.storage import save_state
        save_state(state)

    elif target == "routing_stats":
        # Record a routing observation (no file write needed)
        pass

    else:
        return {"error": f"unknown target: {target}"}

    return rollback


# ── Versioning ────────────────────────────────────────────────

class VersionBumpKind(Enum):
    """Types of version bumps applied to the self-improvement state."""
    MINOR = "minor"  # new candidate, observation
    MAJOR = "major"  # approved change applied
    ROLLBACK = "rollback"  # improvement rolled back


@dataclass(frozen=True)
class VersionInfo:
    """Immutable version info for an improvement change."""
    version: str  # semantic version string e.g. "1.2.3"
    bump_kind: VersionBumpKind
    description: str
    applied_at: float = field(default_factory=time.monotonic)

    @staticmethod
    def next_version(previous: str | None, bump: VersionBumpKind) -> str:
        """Increment semantic version string."""
        if not previous or previous == "0.0.0":
            parts = [0, 0, 0]
        else:
            parts = [int(p) for p in previous.split(".")]
            if len(parts) < 3:
                parts = parts + [0] * (3 - len(parts))
        if bump == VersionBumpKind.MINOR:
            parts[2] += 1
        elif bump == VersionBumpKind.MAJOR:
            parts[1] += 1
            parts[2] = 0
        elif bump == VersionBumpKind.ROLLBACK:
            parts[0] += 1
            parts[1] = 0
            parts[2] = 0
        return f"{parts[0]}.{parts[1]}.{parts[2]}"


# ── Audit Log (immutable, append-only) ────────────────────────

class AuditAction(Enum):
    """Actions logged to the immutable audit trail."""
    OBSERVATION = "observation"
    CANDIDATE_GENERATED = "candidate_generated"
    CANDIDATE_APPROVED = "candidate_approved"
    CANDIDATE_REJECTED = "candidate_rejected"
    CANDIDATE_EVAL_FAILED = "evaluation_failed"
    CHANGE_APPLIED = "change_applied"
    CHANGE_ROLLED_BACK = "change_rolled_back"
    SECURITY_VIOLATION_BLOCKED = "security_violation_blocked"


@dataclass(frozen=True)
class AuditEvent:
    """Immutable append-only audit log entry."""
    sequence: int
    action: AuditAction
    target_id: str  # candidate ID or system-wide
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)
    actor: str = "system"  # "system", "user", or specific user ID

    def to_dict(self) -> dict[str, Any]:
        d = {
            "sequence": self.sequence,
            "action": self.action.value,
            "target_id": self.target_id,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "actor": self.actor,
        }
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AuditEvent":
        return AuditEvent(
            sequence=d["sequence"],
            action=AuditAction(d["action"]),
            target_id=d["target_id"],
            detail=d.get("detail", {}),
            timestamp=d.get("timestamp", 0.0),
            actor=d.get("actor", "system"),
        )


# ── Evaluation ────────────────────────────────────────────────

class EvaluationResult(Enum):
    """Result of a safe-evaluation step."""
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True)
class EvaluationRecord:
    """Result of evaluating a candidate against security and safety constraints."""
    candidate_id: str
    result: EvaluationResult
    checked_by: str = "security_guard"
    checks_run: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.monotonic)
    notes: str = ""

    def is_safe_to_apply(self) -> bool:
        return self.result == EvaluationResult.PASS


# ── Security Guardrails ───────────────────────────────────────

class SecurityPolicyViolation(Enum):
    """Violations that the security guardrails check for."""
    AUTH_WEAKENING = "auth_weakening"
    APPROVAL_WEAKENING = "approval_weakening"
    PERMISSION_REDUCTION = "permission_reduction"
    NETWORK_EXPOSURE = "network_exposure_increase"
    SECRET_PERSISTENCE = "secret_persistence"
    SECURITY_POLICY_CHANGE = "security_policy_change"


@dataclass(frozen=True)
class SecurityCheckResult:
    """Result of a security policy check."""
    violation: SecurityPolicyViolation | None = None
    detail: str = ""

    @property
    def safe(self) -> bool:
        return self.violation is None


def check_security_policy(change: dict[str, Any]) -> SecurityCheckResult:
    """Check if a proposed change violates any security policy.

    Returns a SecurityCheckResult with violation details if the change
    would weaken authentication, approvals, permissions, network exposure,
    persist secrets, or modify security policy.

    This is the gatekeeper that makes the self-improvement pipeline safe.
    """
    target = change.get("target", "")
    action = change.get("action", "")

    # Block any change that explicitly references security-sensitive configs
    sensitive_targets = {
        "security_policy", "auth_config", "permission_policy",
        "approval_workflow", "network_rules", "secret_keys",
        "encryption_keys", "api_keys_config", "firewall_rules",
    }
    if target in sensitive_targets:
        return SecurityCheckResult(
            violation=SecurityPolicyViolation.SECURITY_POLICY_CHANGE,
            detail=f"Cannot self-improve on security policy target: {target}",
        )

    # Check for network exposure increase
    if target == "network" or (action in ("open_port", "disable_firewall", "allow_public")):
        return SecurityCheckResult(
            violation=SecurityPolicyViolation.NETWORK_EXPOSURE,
            detail="Self-improvement cannot increase network exposure",
        )

    # Check for secret persistence
    if target == "secrets" or action in ("save_secret", "persist_api_key"):
        return SecurityCheckResult(
            violation=SecurityPolicyViolation.SECRET_PERSISTENCE,
            detail="Self-improvement cannot persist secrets",
        )

    # Check for auth weakening (via config target)
    if target == "config":
        key = change.get("key", "")
        if key in ("require_auth", "require_approval", "permission_check",
                    "security_level", "auth_mandatory", "approval_required"):
            old_val = change.get("_old_value")
            new_val = change.get("value")
            if old_val is True and new_val is False:
                return SecurityCheckResult(
                    violation=SecurityPolicyViolation.APPROVAL_WEAKENING,
                    detail=f"Cannot weaken {key}: True → False",
                )

    return SecurityCheckResult()


# ── Monitoring ──────────────────────────────────────────────

class MonitorStatus(Enum):
    """Status of post-apply monitoring for an improvement."""
    NOT_MONITORED = "not_monitored"
    MONITORING = "monitoring"
    CONFIRMED_BENEFICIAL = "confirmed_beneficial"
    DEGRADATION_DETECTED = "degradation_detected"


@dataclass
class MonitoringSnapshot:
    """Captures before/after metrics for an applied improvement."""
    candidate_id: str
    before_snapshot: dict[str, Any] = field(default_factory=dict)
    after_snapshot: dict[str, Any] = field(default_factory=dict)
    status: MonitorStatus = MonitorStatus.NOT_MONITORED
    degradation_detected: bool = False
    degradation_reason: str = ""
    monitoring_started_at: float = field(default_factory=time.monotonic)
    monitoring_ended_at: float | None = None

    def detect_degradation(self, threshold_pct: float = 10.0) -> bool:
        """Check if degradation was detected by comparing snapshots.

        Compares key metrics between before/after snapshots.
        A degradation is detected if any metric degraded by more than threshold_pct.
        """
        before = self.before_snapshot
        after = self.after_snapshot
        degraded_metrics: list[str] = []

        for key in before:
            if key not in after:
                degraded_metrics.append(f"{key}: missing in after")
                continue
            before_val = before[key]
            after_val = after[key]
            if isinstance(before_val, (int, float)) and isinstance(after_val, (int, float)):
                if before_val != 0:
                    pct_change = abs(before_val - after_val) / abs(before_val) * 100
                    if pct_change > threshold_pct:
                        degraded_metrics.append(
                            f"{key}: {before_val} → {after_val} ({pct_change:.1f}% change)"
                        )
            elif before_val != after_val:
                degraded_metrics.append(f"{key}: {before_val} → {after_val}")

        if degraded_metrics:
            self.degradation_detected = True
            self.degradation_reason = "; ".join(degraded_metrics[:3])
            self.status = MonitorStatus.DEGRADATION_DETECTED
            return True

        self.status = MonitorStatus.CONFIRMED_BENEFICIAL
        return False
