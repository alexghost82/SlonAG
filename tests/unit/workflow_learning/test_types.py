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

    def test_from_tool_result_minimal(self):
        step = WorkflowStep.from_tool_result(
            tool_name="shell_exec",
            args={"cmd": "ls"},
            ok=True,
        )
        assert step.tool_name == "shell_exec"
        assert step.ok is True
        assert step.message == ""
        assert step.data is None
        assert step.artifacts == []


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

    def test_cannot_skip_stages(self):
        """Should not be able to skip from DRAFT directly to ACTIVE or PARAMETERIZED."""
        c = WorkflowCandidate(name="test")
        with pytest.raises(ValueError):
            c.transition_to(WorkflowState.ACTIVE)
        with pytest.raises(ValueError):
            c.transition_to(WorkflowState.PARAMETERIZED)

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
        assert c.is_terminal is False  # APPROVED is not terminal

        c.transition_to(WorkflowState.DEPRECATED)
        assert c.is_terminal is True  # DEPRECATED is terminal

        c.transition_to(WorkflowState.APPROVED)
        assert c.is_terminal is False  # Can exit DEPRECATED

    def test_updated_at_changes_on_transition(self):
        c = WorkflowCandidate(name="test")
        before = c.updated_at
        c.transition_to(WorkflowState.CANDIDATE)
        assert c.updated_at >= before


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

    def test_from_string(self):
        assert WorkflowState("draft") == WorkflowState.DRAFT
        assert WorkflowState("active") == WorkflowState.ACTIVE


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

    def test_with_step_results(self):
        r = ExecutionResult(
            workflow_id="abc123",
            template_version=1,
            step_results=[
                StepExecutionResult(step_index=0, tool_name="shell_exec", ok=True),
                StepExecutionResult(step_index=1, tool_name="file_write", ok=False, message="denied"),
            ],
        )
        assert len(r.step_results) == 2
        assert r.ok is True  # Initial state
        r.mark_failed("final error")
        assert r.ok is False


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

    def test_failed_sequence(self):
        seq = ActionSequence(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"command": "ls"}, ok=True),
                WorkflowStep(tool_name="file_write", args={"path": "/tmp/x"}, ok=False),
            ],
            success=False,
        )
        assert seq.success is False


class TestWorkflowTemplate:
    """Tests for WorkflowTemplate model."""

    def test_initial(self):
        t = WorkflowTemplate(
            id="abc123",
            version=1,
            name="test-template",
            description="Test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[],
        )
        assert t.name == "test-template"
        assert t.is_active is True

    def test_not_active(self):
        t = WorkflowTemplate(
            id="abc123",
            version=1,
            name="test",
            description="Test",
            state=WorkflowState.DRAFT,
            parameter_slots=[],
            step_descriptors=[],
        )
        assert t.is_active is False


class TestStepDescriptor:
    """Tests for StepDescriptor model."""

    def test_defaults(self):
        sd = StepDescriptor(
            tool_name="shell_exec",
            arg_template={"cmd": {"_slot": "command", "_type": "string"}},
            required_slots=["command"],
        )
        assert sd.tool_name == "shell_exec"
        assert sd.required_slots == ["command"]
        assert sd.safety_risk == 0


class TestExecutionRecord:
    """Tests for ExecutionRecord model."""

    def test_initial(self):
        r = ExecutionRecord(workflow_id="abc123", template_version=1)
        assert r.workflow_id == "abc123"
        assert r.template_version == 1
        assert r.created_at > 0


class TestActionSequenceEvent:
    """Tests for ActionSequenceEvent model."""

    def test_basic(self):
        event = ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "ls"})
        assert event.tool_name == "shell_exec"
        assert event.args == {"cmd": "ls"}
        assert event.tool_call_id is None
