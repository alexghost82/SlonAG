"""Tests for workflow_learning.types."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from mark.workflow_learning.types import (
    ActionSequence,
    ActionSequenceEvent,
    ApprovalResult,
    ExecutionRecord,
    ExecutionResult,
    ParameterSlot,
    StepDescriptor,
    StepExecutionResult,
    WorkflowCandidate,
    WorkflowState,
    WorkflowStep,
    WorkflowTemplate,
)


class TestWorkflowStep:
    """Tests for WorkflowStep model."""

    def test_from_tool_result(self):
        step = WorkflowStep.from_tool_result(
            tool_name="shell_exec",
            args={"command": "ls -la"},
            ok=True,
            message="success",
            data={"exit_code": 0},
            started_at=100.0,
            finished_at=101.0,
        )
        assert step.tool_name == "shell_exec"
        assert step.args == {"command": "ls -la"}
        assert step.ok is True
        assert step.message == "success"
        assert step.data == {"exit_code": 0}
        assert step.started_at == 100.0
        assert step.finished_at == 101.0

    def test_from_tool_result_with_artifacts(self):
        step = WorkflowStep.from_tool_result(
            tool_name="file_write",
            args={"path": "/tmp/test.txt", "content": "hello"},
            ok=True,
            message="written",
            artifacts=[{"kind": "file", "path": "/tmp/test.txt"}],
        )
        assert step.artifacts == [{"kind": "file", "path": "/tmp/test.txt"}]


class TestWorkflowCandidate:
    """Tests for WorkflowCandidate state machine."""

    def test_initial_state_is_draft(self):
        c = WorkflowCandidate(name="test")
        assert c.state == WorkflowState.DRAFT
        assert c.version == 1
        assert c.confidence == 0.0

    def test_transition_draft_to_candidate(self):
        c = WorkflowCandidate(name="test")
        c.transition_to(WorkflowState.CANDIDATE)
        assert c.state == WorkflowState.CANDIDATE
        assert c.approved_at is None

    def test_transition_candidate_to_approved(self):
        c = WorkflowCandidate(name="test")
        c.transition_to(WorkflowState.CANDIDATE)
        c.transition_to(WorkflowState.APPROVED)
        assert c.state == WorkflowState.APPROVED
        assert c.approved_at is not None

    def test_transition_approved_to_parameterized(self):
        c = WorkflowCandidate(name="test")
        c.transition_to(WorkflowState.APPROVED)
        c.transition_to(WorkflowState.PARAMETERIZED)
        assert c.state == WorkflowState.PARAMETERIZED

    def test_transition_parameterized_to_active(self):
        c = WorkflowCandidate(name="test")
        c.transition_to(WorkflowState.APPROVED)
        c.transition_to(WorkflowState.PARAMETERIZED)
        c.transition_to(WorkflowState.ACTIVE)
        assert c.state == WorkflowState.ACTIVE

    def test_transition_active_to_deprecated(self):
        c = WorkflowCandidate(name="test")
        c.transition_to(WorkflowState.ACTIVE)
        c.transition_to(WorkflowState.DEPRECATED)
        assert c.state == WorkflowState.DEPRECATED

    def test_cannot_reject_draft(self):
        c = WorkflowCandidate(name="test")
        with pytest.raises(ValueError):
            c.transition_to(WorkflowState.DEPRECATED)

    def test_cannot_reactivate_deprecated(self):
        c = WorkflowCandidate(name="test")
        c.transition_to(WorkflowState.APPROVED)
        c.transition_to(WorkflowState.DEPRECATED)
        with pytest.raises(ValueError):
            c.transition_to(WorkflowState.CANDIDATE)

    def test_is_terminal(self):
        c = WorkflowCandidate(name="test")
        assert c.is_terminal is False

        c.transition_to(WorkflowState.APPROVED)
        assert c.is_terminal is True

        c.transition_to(WorkflowState.DEPRECATED)
        assert c.is_terminal is True

    def test_updated_at_changes_on_transition(self):
        c = WorkflowCandidate(name="test")
        before = c.updated_at
        time.sleep(0.01)
        c.transition_to(WorkflowState.CANDIDATE)
        assert c.updated_at > before


class TestWorkflowStateEnum:
    """Tests for WorkflowState enum values."""

    def test_all_states_present(self):
        assert WorkflowState.DRAFT == "draft"
        assert WorkflowState.CANDIDATE == "candidate"
        assert WorkflowState.APPROVED == "approved"
        assert WorkflowState.PARAMETERIZED == "parameterized"
        assert WorkflowState.ACTIVE == "active"
        assert WorkflowState.DEPRECATED == "deprecated"

    def test_iteration(self):
        states = list(WorkflowState)
        assert len(states) == 6


class TestParameterSlot:
    """Tests for ParameterSlot model."""

    def test_defaults(self):
        slot = ParameterSlot(name="filename", slot_type="path")
        assert slot.name == "filename"
        assert slot.slot_type == "path"
        assert slot.required is True
        assert slot.default is None
        assert slot.description == ""

    def test_custom(self):
        slot = ParameterSlot(
            name="count",
            slot_type="int",
            required=False,
            default=10,
            description="Number of items",
        )
        assert slot.required is False
        assert slot.default == 10
        assert slot.description == "Number of items"


class TestExecutionResult:
    """Tests for ExecutionResult model."""

    def test_initial(self):
        r = ExecutionResult(workflow_id="abc123", template_version=1)
        assert r.ok is True
        assert r.error == ""
        assert len(r.step_results) == 0

    def test_mark_failed(self):
        r = ExecutionResult(workflow_id="abc123", template_version=1)
        r.mark_failed("some error")
        assert r.ok is False
        assert r.error == "some error"


class TestApprovalResult:
    """Tests for ApprovalResult model."""

    def test_defaults(self):
        a = ApprovalResult(step_index=0, tool_name="shell_exec", allowed=True)
        assert a.step_index == 0
        assert a.tool_name == "shell_exec"
        assert a.allowed is True
        assert a.reason == ""
        assert a.risk == 0


class TestActionSequence:
    """Tests for ActionSequence model."""

    def test_initial(self):
        seq = ActionSequence()
        assert len(seq.steps) == 0
        assert seq.success is True
        assert seq.created_at > 0

    def test_with_steps(self):
        seq = ActionSequence(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"command": "ls"}, ok=True),
                WorkflowStep(tool_name="file_write", args={"path": "/tmp/x"}, ok=True),
            ],
            success=True,
        )
        assert len(seq.steps) == 2
        assert seq.success is True
