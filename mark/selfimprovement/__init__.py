"""Controlled Self-Improvement — SlonAG.

Observation → improvement candidate → evidence → evaluation → approval →
apply bounded change → monitor → rollback.

All changes are observable, readable, and logged.
"""

from __future__ import annotations

from mark.selfimprovement.types import (
    AuditAction,
    AuditEntry,
    EvidenceType,
    EvaluationStatus,
    ImprovementCandidate,
    ImprovementCategory,
    ImprovementStatus,
    MetricBucket,
    MetricKind,
    MetricSnapshot,
    Observation,
    ObservationKind,
    RiskLevel,
    SelfImprovementRecord,
    SelfImprovementState,
    apply_bounded_change,
)
from mark.selfimprovement.collector import MetricsCollector
from mark.selfimprovement.rules import generate_candidates
from mark.selfimprovement.pipeline import SelfImprovementPipeline
from mark.selfimprovement.storage import _load_state, _save_state
from mark.selfimprovement import localized_strings

__all__ = [
    # Types
    "ImprovementCandidate",
    "ImprovementCategory",
    "ImprovementStatus",
    "Observation",
    "ObservationKind",
    "MetricKind",
    "MetricSnapshot",
    "MetricBucket",
    "SelfImprovementState",
    "SelfImprovementRecord",
    "RiskLevel",
    "EvidenceType",
    "apply_bounded_change",
    # Pipeline
    "SelfImprovementPipeline",
    "generate_candidates",
    # Collector
    "MetricsCollector",
    "get_collector",
    "load_state",
    "save_state",
    # Audit
    "AuditAction",
    "AuditEntry",
    "EvaluationStatus",
    # Localization
    "localized_strings",
]


# --- default singletons ---

_state: SelfImprovementState | None = None
_collector: MetricsCollector | None = None


def get_collector() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


def load_state(path: str | None = None) -> SelfImprovementState:
    global _state
    if _state is not None:
        return _state
    _state = _load_state(path)
    return _state


def save_state(path: str | None = None) -> None:
    global _state
    if _state is None:
        return
    _save_state(_state, path)
