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
    """Persistent state for the self-improvement system."""
    observations_count: int = 0
    candidates_generated: int = 0
    approved_count: int = 0
    rolled_back_count: int = 0
    improvements: dict[str, SelfImprovementRecord] = field(default_factory=dict)

    def register_observation(self) -> None:
        self.observations_count += 1

    def register_candidate(self) -> None:
        self.candidates_generated += 1

    def register_approval(self) -> None:
        self.approved_count += 1

    def register_rollback(self) -> None:
        self.rolled_back_count += 1


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
        from mark.selfimprovement import save_state
        save_state(state)

    elif target == "routing_stats":
        # Record a routing observation (no file write needed)
        pass

    else:
        return {"error": f"unknown target: {target}"}

    return rollback
