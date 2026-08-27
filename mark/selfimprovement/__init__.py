"""Controlled Self-Improvement — SlonAG.

Observation → improvement candidate → evidence → expected benefit → risk →
approval → apply bounded change → monitor → rollback.

All changes are observable, reversible, and logged.
"""

from __future__ import annotations

from mark.selfimprovement.types import (
    ImprovementCandidate,
    ImprovementStatus,
    MetricBucket,
    MetricKind,
    MetricSnapshot,
    Observation,
    ObservationKind,
    SelfImprovementRecord,
    SelfImprovementState,
    apply_bounded_change,
)
from mark.selfimprovement.collector import MetricsCollector
from mark.selfimprovement.rules import generate_candidates
from mark.selfimprovement.pipeline import SelfImprovementPipeline

__all__ = [
    "ImprovementCandidate",
    "ImprovementStatus",
    "MetricBucket",
    "MetricKind",
    "MetricSnapshot",
    "Observation",
    "ObservationKind",
    "SelfImprovementRecord",
    "SelfImprovementState",
    "SelfImprovementPipeline",
    "apply_bounded_change",
    "generate_candidates",
    "get_collector",
    "load_state",
    "save_state",
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
    from mark.selfimprovement.storage import load_state as _load

    _state = _load(path)
    return _state


def save_state(path: str | None = None) -> None:
    global _state
    if _state is None:
        return
    from mark.selfimprovement.storage import save_state as _save

    _save(_state, path)
