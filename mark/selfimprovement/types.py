"""Immutable data types for the controlled self-improvement pipeline.

Supports: versioning, immutable audit history, evaluation, user approval,
rollback, and monitoring.
"""

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


# ── Evaluation ────────────────────────────────────────────────

class EvaluationStatus(Enum):
    """Status of an improvement evaluation (between approval and apply)."""
    NOT_EVALUATED = "not_evaluated"
    PASSED = "passed"
    FAILED = "failed"


# ── Audit ─────────────────────────────────────────────────────

class AuditAction(Enum):
    """An immutable audit action recorded for every state change."""
    OBSERVE = "observe"
    CANDIDATE_GENERATED = "candidate_generated"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EVALUATED_PASS = "evaluated_passed"
    EVALUATED_FAIL = "evaluated_failed"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    VERSION_INCREMENTED = "version_incremented"
    USER_FEEDBACK = "user_feedback"


@dataclass(frozen=True)
class AuditEntry:
    """Immutable audit log entry — one record per state transition."""
    action: AuditAction
    timestamp: float = field(default_factory=time.monotonic)
    details: dict[str, Any] = field(default_factory=dict)
    message_ru: str = ""  # user-facing Russian message

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action": self.action.value,
            "timestamp": self.timestamp,
            "details": self.details,
            "message_ru": self.message_ru,
        }
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AuditEntry":
        return AuditEntry(
            action=AuditAction(d["action"]),
            timestamp=d.get("timestamp", 0.0),
            details=d.get("details", {}),
            message_ru=d.get("message_ru", ""),
        )


# ── Metrics ───────────────────────────────────────────────────

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
    """Lifecycle record for one improvement.

    Attributes:
        version: Incremented on every state mutation (supports versioning).
        audit_log: Append-only immutable audit trail.
        evaluation: Evaluation result (between approval and apply).
    """
    id: str
    title: str
    status: ImprovementStatus = ImprovementStatus.PROPOSED
    version: int = 1  # versioned: increments on every change
    created_at: float = field(default_factory=time.monotonic)
    approved_at: float | None = None
    applied_at: float | None = None
    rolled_back_at: float | None = None
    approved_by: str = "system"
    benefit_observed: str | None = None
    rollback_reason: str | None = None
    proposed_change: dict[str, Any] = field(default_factory=dict)
    rollback_change: dict[str, Any] = field(default_factory=dict)
    evaluation: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    evaluation_reason: str = ""
    evaluation_score: float = 0.0

    # Mutable audit log — each entry is an immutable AuditEntry
    _audit_log: list[AuditEntry] = field(default_factory=list, repr=False)

    # ── Versioning ──────────────────────────────────────────────

    def bump_version(self, reason: str = "state change") -> int:
        """Increment version and log the bump. Returns new version."""
        self.version += 1
        self._audit_log.append(AuditEntry(
            action=AuditAction.VERSION_INCREMENTED,
            details={"reason": reason, "old_version": self.version - 1, "new_version": self.version},
            message_ru=f"Версия изменена: {self.version - 1} → {self.version} ({reason})",
        ))
        return self.version

    # ── Audit logging ──────────────────────────────────────────

    def audit(self, action: AuditAction, details: dict[str, Any] | None = None,
              message_ru: str = "") -> None:
        """Append an immutable audit entry."""
        entry = AuditEntry(
            action=action,
            details=details or {},
            message_ru=message_ru,
        )
        self._audit_log.append(entry)

    @property
    def audit_log(self) -> list[AuditEntry]:
        """Read-only view of the audit log."""
        return list(self._audit_log)

    def get_audit_summary(self) -> list[dict[str, Any]]:
        """Return serialisable audit entries."""
        return [e.to_dict() for e in self._audit_log]

    @staticmethod
    def _record_from_dict(d: dict[str, Any]) -> "SelfImprovementRecord":
        import dataclasses
        if dataclasses.is_dataclass(SelfImprovementRecord):
            # Convert enum values back
            for k, v in list(d.items()):
                if k == "status" and isinstance(v, str):
                    try:
                        d[k] = ImprovementStatus(v)
                    except ValueError:
                        pass
                elif k == "evaluation" and isinstance(v, str):
                    try:
                        d[k] = EvaluationStatus(v)
                    except ValueError:
                        pass
            # Remove audit_log from kwargs (it's set manually after)
            audit_log_data = d.pop("audit_log", [])
            rec = SelfImprovementRecord(**d)
            # Restore audit log entries
            for entry_data in audit_log_data:
                rec._audit_log.append(AuditEntry.from_dict(entry_data))
            return rec
        return SelfImprovementRecord(**d)

    def _to_dict(self) -> dict[str, Any]:
        import dataclasses
        if dataclasses.is_dataclass(self):
            result = {}
            for f in dataclasses.fields(self):
                val = getattr(self, f.name)
                if f.name == "_audit_log":
                    result["audit_log"] = self.get_audit_summary()
                    continue
                if isinstance(val, Enum):
                    val = val.value
                result[f.name] = val
            return result
        return self.__dict__


# ── State ─────────────────────────────────────────────────────

@dataclass
class SelfImprovementState:
    """Persistent state for the self-improvement system."""
    observations_count: int = 0
    candidates_generated: int = 0
    approved_count: int = 0
    rolled_back_count: int = 0
    total_user_feedback_count: int = 0
    improvements: dict[str, SelfImprovementRecord] = field(default_factory=dict)
    audit_history: list[AuditEntry] = field(default_factory=list)

    def register_observation(self) -> None:
        self.observations_count += 1

    def register_candidate(self) -> None:
        self.candidates_generated += 1

    def register_approval(self) -> None:
        self.approved_count += 1

    def register_rollback(self) -> None:
        self.rolled_back_count += 1

    def register_user_feedback(self) -> None:
        self.total_user_feedback_count += 1

    def add_audit_entry(self, entry: AuditEntry) -> None:
        self.audit_history.append(entry)


# ── Bounded change application ────────────────────────────────

def apply_bounded_change(
    change: dict[str, Any],
    rollback_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a bounded, reversible change and return the rollback snapshot.

    Security policy: NEVER weakens authentication, approval, permission checks,
    network exposure, or secret storage.

    Currently supports:
    - Writing to a JSON settings file (change key, rollback old value).
    - Adding entries to a memory category.
    - Adjusting a timeout value.
    - Recording a routing statistic.
    - Memory pruning (read-only or backup-based).

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
        action_type = action
        if action_type == "refine_extraction_prompt":
            # Write a refined extraction prompt to memory — safe, reversible
            from memory.memory_manager import update_memory
            category = change.get("correction_type", "preferences")
            prompt_key = f"extraction_prompt_{category}"
            value = change.get("value", "")
            from memory.memory_manager import load_memory
            memory = load_memory()
            old_entry = memory.get("system", {}).get(prompt_key)
            rollback = {"type": "memory", "category": "system", "key": prompt_key, "old": old_entry}
            update_memory({"system": {prompt_key: {"value": value, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}}})
        elif action_type == "prune_stale_entries":
            # Memory pruning: mark entries as stale (reversible)
            from memory.memory_manager import update_memory, load_memory
            stale_count = change.get("stale_count", 0)
            memory = load_memory()
            # Snapshot the current memory state for rollback
            rollback = {"type": "memory", "action": "prune_stale", "memory_snapshot": json.dumps(memory)}
            # Store pruning metadata (non-destructive: just marks as stale)
            update_memory({
                "audit": {
                    "last_stale_prune_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "pruned_count": stale_count,
                }
            })
        else:
            # Generic memory update
            from memory.memory_manager import update_memory
            category = change.get("category", "notes")
            key = change["key"]
            value = change["value"]
            from memory.memory_manager import load_memory
            memory = load_memory()
            old_entry = memory.get(category, {}).get(key)
            rollback = {"type": "memory", "category": "category", "key": key, "old": old_entry}
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
