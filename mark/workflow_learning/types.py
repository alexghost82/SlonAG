"""Core data models for workflow learning.

All models are serializable to/from JSON for persistence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkflowState(StrEnum):
    """Lifecycle states for a workflow candidate/template."""

    DRAFT = "draft"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    PARAMETERIZED = "parameterized"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class WorkflowVersionMode(StrEnum):
    """How to handle versions on store update."""

    NEW = "new"
    INCREMENT = "increment"


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


@dataclass
class WorkflowStep:
    """A single tool execution within an observed sequence."""

    tool_name: str
    args: dict[str, Any]
    ok: bool
    message: str = ""
    data: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    approval_started_at: float | None = None
    approval_finished_at: float | None = None
    handler_started_at: float | None = None

    @classmethod
    def from_tool_result(
        cls,
        *,
        tool_name: str,
        args: dict[str, Any],
        ok: bool,
        message: str = "",
        data: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        **timing: float | None,
    ) -> WorkflowStep:
        """Build a WorkflowStep from a tool execution result."""
        return cls(
            tool_name=tool_name,
            args=args,
            ok=ok,
            message=message,
            data=data,
            artifacts=artifacts or [],
            started_at=timing.get("started_at"),
            finished_at=timing.get("finished_at"),
            approval_started_at=timing.get("approval_started_at"),
            approval_finished_at=timing.get("approval_finished_at"),
            handler_started_at=timing.get("handler_started_at"),
        )


@dataclass
class ActionSequenceEvent:
    """A single action observation event from the executor pipeline."""

    tool_name: str
    args: dict[str, Any]
    tool_call_id: str | None = None


@dataclass
class ActionSequence:
    """A complete observed sequence of tool executions."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    steps: list[WorkflowStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    session_id: str | None = None
    user_intent: str = ""
    success: bool = True
    total_duration: float = 0.0


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------


@dataclass
class ParameterSlot:
    """A named parameter slot extracted during normalization."""

    name: str
    slot_type: str  # "string", "path", "url", "int", "float", "boolean"
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class WorkflowCandidate:
    """A learned workflow candidate awaiting user review.

    State machine:
        DRAFT -> CANDIDATE (enough repetitions observed)
        CANDIDATE -> APPROVED (user confirmed)
        APPROVED -> PARAMETERIZED (normalized + template extracted)
        PARAMETERIZED -> ACTIVE (used in production)
        Any -> DEPRECATED (replaced)
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    description: str = ""
    version: int = 1
    state: WorkflowState = WorkflowState.DRAFT
    steps: list[WorkflowStep] = field(default_factory=list)
    parameter_slots: list[ParameterSlot] = field(default_factory=list)
    confidence: float = 0.0
    repetition_count: int = 0
    successful_executions: int = 0
    total_executions: int = 0
    provenance: str = ""  # source of learning (e.g., session ID)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    approved_at: float | None = None
    approved_by: str = ""
    parent_candidate_id: str | None = None
    notes: str = ""

    @property
    def is_terminal(self) -> bool:
        """Return True if workflow is in a terminal state.

        DEPRECATED is the only truly terminal state — workflows
        in APPROVED, PARAMETERIZED, or ACTIVE can still transition
        (e.g. ACTIVE -> DEPRECATED).
        """
        return self.state == WorkflowState.DEPRECATED

    def transition_to(self, new_state: WorkflowState) -> None:
        """Move to a new state, enforcing the state machine.

        State flow:
            DRAFT -> CANDIDATE -> APPROVED -> PARAMETERIZED -> ACTIVE
            DRAFT -> DEPRECATED          CANDIDATE -> DEPRECATED
            APPROVED -> DEPRECATED       PARAMETERIZED -> DEPRECATED
            ACTIVE -> DEPRECATED
            DEPRECATED -> DRAFT | APPROVED (re-examination only)
        """
        allowed = {
            WorkflowState.DRAFT: {WorkflowState.CANDIDATE, WorkflowState.APPROVED, WorkflowState.ACTIVE, WorkflowState.DEPRECATED},
            WorkflowState.CANDIDATE: {
                WorkflowState.APPROVED,
                WorkflowState.DEPRECATED,
            },
            WorkflowState.APPROVED: {
                WorkflowState.PARAMETERIZED,
                WorkflowState.DEPRECATED,
            },
            WorkflowState.PARAMETERIZED: {
                WorkflowState.ACTIVE,
                WorkflowState.DEPRECATED,
            },
            WorkflowState.ACTIVE: {
                WorkflowState.DEPRECATED,
            },
            WorkflowState.DEPRECATED: {
                WorkflowState.DRAFT,
                WorkflowState.APPROVED,
            },
        }
        if new_state not in allowed.get(self.state, set()):
            raise ValueError(
                f"Cannot transition from {self.state.value} to {new_state.value}"
            )
        self.state = new_state
        self.updated_at = time.time()
        if new_state == WorkflowState.APPROVED:
            self.approved_at = time.time()
            self.approved_by = "user"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


@dataclass
class WorkflowTemplate:
    """A parameterized workflow template ready for execution.

    Parameters are substituted at runtime before each step executes.
    SafetyPolicy/Approval is re-evaluated for every step.
    """

    id: str
    version: int
    name: str
    description: str
    state: WorkflowState
    parameter_slots: list[ParameterSlot]
    step_descriptors: list[StepDescriptor]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_active(self) -> bool:
        return self.state == WorkflowState.ACTIVE


@dataclass
class StepDescriptor:
    """A normalized step without concrete values — only slots and tool refs."""

    tool_name: str
    arg_template: dict[str, Any]  # contains slot references
    required_slots: list[str]
    safety_risk: int = 0  # from registry


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of running a workflow template."""

    workflow_id: str
    template_version: int
    step_results: list[StepExecutionResult] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    parameters_used: dict[str, Any] = field(default_factory=dict)
    approval_results: list[ApprovalResult] = field(default_factory=list)

    def mark_failed(self, error: str) -> None:
        self.ok = False
        self.error = error


@dataclass
class StepExecutionResult:
    """Result of a single step within a workflow execution."""

    step_index: int
    tool_name: str
    ok: bool
    message: str = ""
    data: dict[str, Any] | None = None
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class ApprovalResult:
    """Record of a safety approval decision during workflow execution."""

    step_index: int
    tool_name: str
    allowed: bool
    reason: str = ""
    risk: int = 0
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@dataclass
class ExecutionRecord:
    """Persisted record of a workflow execution run."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    workflow_id: str = ""
    template_version: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)
    result: ExecutionResult | None = None
    created_at: float = field(default_factory=time.time)
    notes: str = ""
