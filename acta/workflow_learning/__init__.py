"""Production workflow learning module for SlonAG.

Observes agent tool-use sequences, normalizes them, computes confidence,
and turns frequently successful patterns into reusable parameterized workflows.

Key principles
--------------
* Every execution re-evaluates SafetyPolicy/Approval — no cached or inherited
  approvals survive across runs.
* Candidates start in ``DRAFT`` state until a user explicitly approves them.
* Approved workflows are stored as parameterized templates with versioning.
* Execution re-runs the full safety pipeline for each step.
"""

from __future__ import annotations

from .types import (
    ActionSequence,
    ActionSequenceEvent,
    ExecutionRecord,
    WorkflowCandidate,
    WorkflowState,
    WorkflowStep,
    WorkflowTemplate,
)
from .observer import ActionObserver
from .normalizer import Normalizer
from .confidence import ConfidenceEngine
from .store import WorkflowStore
from .executor import WorkflowExecutor
from .service import WorkflowService

__all__ = [
    "ActionObserver",
    "ActionSequence",
    "ActionSequenceEvent",
    "ConfidenceEngine",
    "ExecutionRecord",
    "ExecutionResult",
    "Normalizer",
    "WorkflowCandidate",
    "WorkflowExecutor",
    "WorkflowService",
    "WorkflowState",
    "WorkflowStep",
    "WorkflowStore",
    "WorkflowTemplate",
    "create_workflow_service",
]


def create_workflow_service(
    *,
    store_path: str | None = None,
    observation_store_path: str | None = None,
    min_repetitions: int = 3,
    observation_buffer_size: int = 20,
) -> WorkflowService:
    """Factory to create a fully wired WorkflowService."""
    store = WorkflowStore(store_path=store_path)
    observer = ActionObserver(
        store=store,
        min_repetitions=min_repetitions,
        buffer_size=observation_buffer_size,
    )
    normalizer = Normalizer()
    confidence = ConfidenceEngine()
    executor = WorkflowExecutor()
    return WorkflowService(
        store=store,
        observer=observer,
        normalizer=normalizer,
        confidence=confidence,
        executor=executor,
    )
