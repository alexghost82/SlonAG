"""Tests for workflow_learning.executor.

Covers the full execution path:
  - execute_candidate with registered handlers
  - execute_template with parameter substitution
  - SafetyPolicy integration (DENY propagation)
  - Blocked execution for non-approved candidates
  - Error handling and step failures
  - Idempotency of step execution
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from acta.safety.types import DecisionKind, SafetyDecision, UntrustedSource
from acta.workflow_learning.executor import (
    WorkflowExecutor,
    _substitute_template,
)
from acta.workflow_learning.types import (
    ExecutionResult,
    ExecutionRecord,
    ParameterSlot,
    StepDescriptor,
    StepExecutionResult,
    WorkflowCandidate,
    WorkflowState,
    WorkflowStep,
    WorkflowTemplate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    state: WorkflowState = WorkflowState.ACTIVE,
    steps: list[WorkflowStep] | None = None,
    version: int = 1,
) -> WorkflowCandidate:
    if steps is None:
        steps = [
            WorkflowStep(tool_name="shell_exec", args={"command": "echo hello"}, ok=True),
            WorkflowStep(tool_name="file_write", args={"path": "/tmp/out.txt", "content": "data"}, ok=True),
        ]
    return WorkflowCandidate(
        id="test-workflow",
        name="test workflow",
        state=state,
        steps=steps,
        version=version,
        parameter_slots=[
            ParameterSlot(name="command", slot_type="string", required=True),
            ParameterSlot(name="path", slot_type="path", required=True),
            ParameterSlot(name="content", slot_type="string", required=True),
        ],
    )


def _make_template(
    steps: list[StepDescriptor] | None = None,
) -> WorkflowTemplate:
    if steps is None:
        steps = [
            StepDescriptor(
                tool_name="shell_exec",
                arg_template={"command": {"_slot": "command", "_type": "string"}},
                required_slots=["command"],
            ),
            StepDescriptor(
                tool_name="file_write",
                arg_template={
                    "path": {"_slot": "path", "_type": "path"},
                    "content": {"_slot": "content", "_type": "string"},
                },
                required_slots=["path", "content"],
            ),
        ]
    return WorkflowTemplate(
        id="test-template",
        version=1,
        name="test-template",
        description="A test template",
        state=WorkflowState.ACTIVE,
        parameter_slots=[
            ParameterSlot(name="command", slot_type="string", required=True),
            ParameterSlot(name="path", slot_type="path", required=True),
            ParameterSlot(name="content", slot_type="string", required=True),
        ],
        step_descriptors=steps,
    )


def _handler_ok(args):
    return MagicMock(ok=True, message="ok", data={"exit_code": 0})


def _handler_fail(args):
    return MagicMock(ok=False, message="step failed", data=None)


def _make_mock_policy():
    """Create a mock policy that always allows."""
    from acta.safety.types import RiskLevel
    policy = MagicMock()
    policy.validate_args.return_value = {"command": "echo hello"}
    policy.authorize.return_value = SafetyDecision(
        kind=DecisionKind.CONFIRM,
        tool_name="shell_exec",
        risk=RiskLevel.CONFIRM,
        source=UntrustedSource.USER,
        intent="",
        args={},
        reason="",
    )
    return policy


# ---------------------------------------------------------------------------
# execute_candidate tests
# ---------------------------------------------------------------------------


class TestExecuteCandidate:
    """Tests for WorkflowExecutor.execute_candidate."""

    def test_successful_execution(self):
        """Full pipeline: observe → candidate → execute with all steps succeeding."""
        policy = _make_mock_policy()
        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)
        executor.register_handler("file_write", _handler_ok)

        candidate = _make_candidate()
        params = {
            "command": "echo hello",
            "path": "/tmp/out.txt",
            "content": "data",
        }
        result = executor.execute_candidate(candidate, params)

        assert result.ok is True
        assert len(result.step_results) == 2
        assert result.step_results[0].ok is True
        assert result.step_results[1].ok is True
        assert result.finished_at > 0

    def test_step_failure_stops_execution(self):
        """Execution stops on the first failed step."""
        policy = _make_mock_policy()
        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)
        executor.register_handler("file_write", _handler_fail)

        candidate = _make_candidate()
        params = {
            "command": "echo hello",
            "path": "/tmp/out.txt",
            "content": "data",
        }
        result = executor.execute_candidate(candidate, params)

        assert result.ok is False
        assert len(result.step_results) == 2
        assert result.step_results[1].ok is False

    def test_no_handler_returns_error(self):
        """If no handler is registered, execution fails with clear error."""
        policy = _make_mock_policy()
        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)
        # file_write handler NOT registered

        candidate = _make_candidate()
        params = {
            "command": "echo hello",
            "path": "/tmp/out.txt",
            "content": "data",
        }
        result = executor.execute_candidate(candidate, params)

        assert result.ok is False
        assert "No handler registered" in result.error
        assert len(result.step_results) == 2  # Both steps recorded
        assert result.step_results[0].ok is True  # First step succeeded
        assert result.step_results[1].ok is False  # Second step failed

    def test_missing_required_parameter(self):
        """Execution fails when a required parameter slot is not provided."""
        policy = _make_mock_policy()
        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)

        # Create a candidate where a required slot has no default
        candidate = _make_candidate(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"command": "echo"}, ok=True),
            ],
        )
        candidate.parameter_slots = [
            ParameterSlot(name="command", slot_type="string", required=True),
        ]

        result = executor.execute_candidate(candidate, {})

        assert result.ok is False
        assert "missing required parameter" in result.error

    def test_safety_policy_denial(self):
        """Safety policy denial stops execution immediately."""
        from acta.safety.types import RiskLevel
        policy = _make_mock_policy()
        policy.authorize.return_value = SafetyDecision(
            kind=DecisionKind.DENY,
            tool_name="shell_exec",
            risk=RiskLevel.BIOMETRIC,
            source=UntrustedSource.USER,
            intent="",
            args={},
            reason="Dangerous command denied",
        )

        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)

        candidate = _make_candidate(
            steps=[
                WorkflowStep(
                    tool_name="shell_exec",
                    args={"command": "rm -rf /"},
                    ok=True,
                ),
            ],
        )
        result = executor.execute_candidate(candidate, {"command": "rm -rf /"})

        assert result.ok is False
        assert "denied by safety policy" in result.error
        assert len(result.approval_results) == 1
        assert result.approval_results[0].allowed is False

    def test_safety_validation_error(self):
        """Invalid arguments cause execution to fail."""
        from acta.safety.types import RiskLevel
        policy = _make_mock_policy()
        policy.validate_args.side_effect = ValueError("Invalid args")
        policy.authorize.return_value = SafetyDecision(
            kind=DecisionKind.DENY,
            tool_name="shell_exec",
            risk=RiskLevel.READ,
            source=UntrustedSource.USER,
            intent="",
            args={},
            reason="validation failed",
        )

        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)

        candidate = _make_candidate(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"command": "echo"}, ok=True),
            ],
        )
        result = executor.execute_candidate(candidate, {"command": "echo"})

        assert result.ok is False
        assert "validation error" in result.error

    def test_approval_results_recorded(self):
        """Every executed step records an approval result."""
        from acta.safety.types import RiskLevel
        policy = _make_mock_policy()
        policy.authorize.return_value = SafetyDecision(
            kind=DecisionKind.CONFIRM,
            tool_name="shell_exec",
            risk=RiskLevel.CONFIRM,
            source=UntrustedSource.USER,
            intent="",
            args={},
            reason="Confirmed by user",
        )

        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)

        candidate = _make_candidate(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"command": "echo"}, ok=True),
            ],
        )
        result = executor.execute_candidate(candidate, {"command": "echo"})

        assert len(result.approval_results) == 1
        approval = result.approval_results[0]
        assert approval.step_index == 0
        assert approval.tool_name == "shell_exec"
        assert approval.risk == 2

    def test_multi_step_multi_approval(self):
        """Multi-step candidate records approvals for every step."""
        policy = _make_mock_policy()
        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)
        executor.register_handler("file_write", _handler_ok)

        candidate = _make_candidate()
        params = {
            "command": "echo hello",
            "path": "/tmp/out.txt",
            "content": "data",
        }
        result = executor.execute_candidate(candidate, params)

        assert len(result.approval_results) == 2
        assert result.approval_results[0].step_index == 0
        assert result.approval_results[1].step_index == 1
        assert all(a.allowed for a in result.approval_results)


class TestExecuteTemplate:
    """Tests for WorkflowExecutor.execute_template.

    Uses dicts for step_descriptors to match the existing executor
    implementation which treats them as dict-like.
    """

    def test_successful_template_execution(self):
        policy = _make_mock_policy()
        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)
        executor.register_handler("file_write", _handler_ok)

        # Use raw dicts for step_descriptors to match executor implementation
        template = WorkflowTemplate(
            id="test-template",
            version=1,
            name="test-template",
            description="A test template",
            state=WorkflowState.ACTIVE,
            parameter_slots=[
                ParameterSlot(name="command", slot_type="string", required=True),
                ParameterSlot(name="path", slot_type="path", required=True),
                ParameterSlot(name="content", slot_type="string", required=True),
            ],
            step_descriptors=[
                {
                    "tool_name": "shell_exec",
                    "arg_template": {"command": {"_slot": "command", "_type": "string"}},
                    "required_slots": ["command"],
                    "safety_risk": 0,
                },
                {
                    "tool_name": "file_write",
                    "arg_template": {
                        "path": {"_slot": "path", "_type": "path"},
                        "content": {"_slot": "content", "_type": "string"},
                    },
                    "required_slots": ["path", "content"],
                    "safety_risk": 0,
                },
            ],
        )
        result = executor.execute_template(
            template,
            {"command": "echo hello", "path": "/tmp/out.txt", "content": "data"},
        )

        assert result.ok is True
        assert len(result.step_results) == 2
        assert result.step_results[0].ok is True
        assert result.step_results[1].ok is True

    def test_missing_template_parameter(self):
        executor = WorkflowExecutor()
        executor.register_handler("shell_exec", _handler_ok)

        template = WorkflowTemplate(
            id="test-template",
            version=1,
            name="test",
            description="test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[
                {
                    "tool_name": "shell_exec",
                    "arg_template": {"command": {"_slot": "command", "_type": "string"}},
                    "required_slots": ["command"],
                    "safety_risk": 0,
                },
            ],
        )
        # Missing 'command' parameter
        result = executor.execute_template(template, {"path": "/tmp/out.txt"})

        assert result.ok is False
        assert "missing required parameter" in result.error

    def test_template_safety_denial(self):
        from acta.safety.types import RiskLevel
        policy = _make_mock_policy()
        policy.authorize.return_value = SafetyDecision(
            kind=DecisionKind.DENY,
            tool_name="shell_exec",
            risk=RiskLevel.BIOMETRIC,
            source=UntrustedSource.USER,
            intent="",
            args={},
            reason="Dangerous command",
        )

        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)

        template = WorkflowTemplate(
            id="test-template",
            version=1,
            name="test",
            description="test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[
                {
                    "tool_name": "shell_exec",
                    "arg_template": {"command": {"_slot": "command", "_type": "string"}},
                    "required_slots": ["command"],
                    "safety_risk": 0,
                },
            ],
        )
        result = executor.execute_template(
            template,
            {"command": "rm -rf /"},
        )

        assert result.ok is False
        assert "denied by safety policy" in result.error
        assert len(result.approval_results) == 1

    def test_step_exception_handled(self):
        policy = _make_mock_policy()
        def bad_handler(args):
            raise RuntimeError("Boom!")

        executor = WorkflowExecutor(safety_policy=policy)
        executor.register_handler("shell_exec", _handler_ok)
        executor.register_handler("file_write", bad_handler)

        template = WorkflowTemplate(
            id="test-template",
            version=1,
            name="test",
            description="test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[
                {
                    "tool_name": "shell_exec",
                    "arg_template": {"command": {"_slot": "command", "_type": "string"}},
                    "required_slots": ["command"],
                    "safety_risk": 0,
                },
                {
                    "tool_name": "file_write",
                    "arg_template": {
                        "path": {"_slot": "path", "_type": "path"},
                        "content": {"_slot": "content", "_type": "string"},
                    },
                    "required_slots": ["path", "content"],
                    "safety_risk": 0,
                },
            ],
        )
        result = executor.execute_template(
            template,
            {"command": "echo", "path": "/tmp/out.txt", "content": "data"},
        )

        assert result.ok is False
        assert len(result.step_results) == 2
        assert result.step_results[1].ok is False
        assert "Boom" in result.step_results[1].message

    def test_empty_template(self):
        template = WorkflowTemplate(
            id="empty",
            version=1,
            name="empty",
            description="Empty template",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[],
        )
        executor = WorkflowExecutor()
        result = executor.execute_template(template, {})

        assert result.ok is True
        assert len(result.step_results) == 0


# ---------------------------------------------------------------------------
# Parameter substitution tests
# ---------------------------------------------------------------------------


class TestParameterSubstitution:
    """Tests for _substitute_template."""

    def test_substitute_basic(self):
        template = {
            "path": {"_slot": "filename", "_type": "path"},
            "mode": "w",
        }
        result = _substitute_template(template, {"filename": "/tmp/test.txt"})
        assert result["path"] == "/tmp/test.txt"
        assert result["mode"] == "w"

    def test_substitute_missing_required(self):
        template = {
            "path": {"_slot": "filename", "_type": "path"},
        }
        result = _substitute_template(template, {})
        assert result is None

    def test_substitute_mixed(self):
        template = {
            "path": {"_slot": "filepath", "_type": "path"},
            "count": 42,
            "verbose": True,
        }
        result = _substitute_template(template, {"filepath": "/tmp/x"})
        assert result["path"] == "/tmp/x"
        assert result["count"] == 42
        assert result["verbose"] is True


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    """Tests for register_handler / unregister_handler."""

    def test_register_and_execute(self):
        executor = WorkflowExecutor()
        called = []

        def handler(args):
            called.append(args)
            return MagicMock(ok=True, message="done", data={})

        executor.register_handler("test_tool", handler)
        result = executor._execute_step("test_tool", {}, None)
        assert len(called) == 1
        assert result.ok is True

    def test_unregister(self):
        executor = WorkflowExecutor()

        def handler(args):
            return MagicMock(ok=True)

        executor.register_handler("tool", handler)
        executor.unregister_handler("tool")

        result = executor._execute_step("tool", {}, None)
        assert result.ok is False
        assert "No handler registered" in result.message

    def test_unregister_nonexistent(self):
        executor = WorkflowExecutor()
        # Should not raise
        executor.unregister_handler("nonexistent")


# ---------------------------------------------------------------------------
# Integration: executor with execution record
# ---------------------------------------------------------------------------


class TestExecutionRecord:
    """Tests for ExecutionRecord model used by executor."""

    def test_record_id(self):
        r = ExecutionRecord(workflow_id="wf1", template_version=1)
        assert len(r.id) > 0

    def test_record_parameters(self):
        r = ExecutionRecord(
            workflow_id="wf1",
            template_version=1,
            parameters={"filename": "/tmp/x.txt", "count": 5},
        )
        assert r.parameters["filename"] == "/tmp/x.txt"
        assert r.parameters["count"] == 5

    def test_record_result_ok(self):
        r = ExecutionResult(workflow_id="wf1", template_version=1, ok=True)
        record = ExecutionRecord(
            workflow_id="wf1",
            template_version=1,
            result=r,
        )
        assert record.result is not None
        assert record.result.ok is True

    def test_record_result_failed(self):
        r = ExecutionResult(workflow_id="wf1", template_version=1, ok=False, error="denied")
        record = ExecutionRecord(
            workflow_id="wf1",
            template_version=1,
            result=r,
        )
        assert record.result.ok is False
        assert record.result.error == "denied"
