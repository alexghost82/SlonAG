"""Workflow execution engine.

Runs parameterized workflows step-by-step. Each step goes through
the full SafetyPolicy + Approval pipeline — no cached approvals.

The executor accepts concrete parameters, substitutes them into
argument templates, and executes each tool call individually.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from mark.safety import SafetyPolicy, authorize, risk_for, validate_args
from mark.safety.types import DecisionKind, SafetyDecision, UntrustedSource

from mark.workflow_learning.types import (
    ApprovalResult,
    ExecutionRecord,
    ExecutionResult,
    ParameterSlot,
    StepDescriptor,
    StepExecutionResult,
    WorkflowCandidate,
    WorkflowTemplate,
)


@dataclass
class _StepTemplate:
    """A single step with substituted parameters."""

    tool_name: str
    args: dict[str, Any]
    required_slots: list[str]


def _substitute_template(
    arg_template: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any] | None:
    """Substitute slot references with actual parameter values.

    Slot references look like: {"_slot": "filename", "_type": "string"}
    Returns None if a required slot is missing.
    """
    result: dict[str, Any] = {}
    for key, value in arg_template.items():
        if isinstance(value, dict) and "_slot" in value:
            slot_name = value["_slot"]
            slot_type = value.get("_type", "string")
            if slot_name not in parameters:
                # Check if there's a default for this slot
                return None  # Missing required parameter
            result[key] = parameters[slot_name]
        else:
            result[key] = value
    return result


class WorkflowExecutor:
    """Execute parameterized workflows with re-authorization."""

    def __init__(
        self,
        safety_policy: SafetyPolicy | None = None,
    ) -> None:
        self._policy = safety_policy or SafetyPolicy()
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._lock = threading.Lock()

    def register_handler(self, tool_name: str, handler: Callable[..., Any]) -> None:
        """Register a handler for a tool (for direct workflow execution)."""
        with self._lock:
            self._handlers[tool_name] = handler

    def unregister_handler(self, tool_name: str) -> None:
        """Remove a registered handler."""
        with self._lock:
            self._handlers.pop(tool_name, None)

    def execute_candidate(
        self,
        candidate: WorkflowCandidate,
        parameters: dict[str, Any],
        *,
        source: UntrustedSource = UntrustedSource.USER,
        intent: str = "",
    ) -> ExecutionResult:
        """Execute a workflow candidate with the given parameters.

        Each step is authorized and approved independently.
        SafetyPolicy is re-evaluated for every step.
        """
        result = ExecutionResult(
            workflow_id=candidate.id,
            template_version=candidate.version,
            started_at=time.time(),
            parameters_used=parameters,
        )

        for idx, step in enumerate(candidate.steps):
            # Build step arguments from the original step, substituting parameters
            step_args = self._prepare_step_args(candidate, idx, parameters)
            if step_args is None:
                result.mark_failed(
                    f"Step {idx + 1} ({step.tool_name}): missing required parameter."
                )
                result.finished_at = time.time()
                return result

            # Safety authorization
            try:
                validated = self._policy.validate_args(step.tool_name, step_args)
            except Exception:
                result.mark_failed(
                    f"Step {idx + 1} ({step.tool_name}): validation error."
                )
                result.finished_at = time.time()
                return result

            decision = self._policy.authorize(
                step.tool_name, validated, source=source, intent=intent
            )

            approval = ApprovalResult(
                step_index=idx,
                tool_name=step.tool_name,
                allowed=decision.kind not in (DecisionKind.DENY,),
                reason=decision.reason,
                risk=decision.risk.value,
            )

            if decision.kind == DecisionKind.DENY:
                result.approval_results.append(approval)
                result.mark_failed(
                    f"Step {idx + 1} ({step.tool_name}): denied by safety policy: {decision.reason}"
                )
                result.finished_at = time.time()
                return result

            result.approval_results.append(approval)

            # Execute the step
            step_result = self._execute_step(
                step.tool_name, validated, step.handler_started_at
            )
            step_result.step_index = idx

            result.step_results.append(step_result)

            if not step_result.ok:
                result.ok = False
                result.error = step_result.message or "Step failed"
                result.finished_at = time.time()
                return result

        result.ok = True
        result.finished_at = time.time()
        return result

    def execute_template(
        self,
        template: WorkflowTemplate,
        parameters: dict[str, Any],
        *,
        source: UntrustedSource = UntrustedSource.USER,
        intent: str = "",
    ) -> ExecutionResult:
        """Execute a workflow template with parameters."""
        result = ExecutionResult(
            workflow_id=template.id,
            template_version=template.version,
            started_at=time.time(),
            parameters_used=parameters,
        )

        for idx, sd in enumerate(template.step_descriptors):
            # Build args from template with parameter substitution
            step_args = _substitute_template(sd["arg_template"], parameters)
            if step_args is None:
                result.mark_failed(
                    f"Step {idx + 1} ({sd['tool_name']}): missing required parameter."
                )
                result.finished_at = time.time()
                return result

            # Safety authorization
            try:
                validated = self._policy.validate_args(sd["tool_name"], step_args)
            except Exception:
                result.mark_failed(
                    f"Step {idx + 1} ({sd['tool_name']}): validation error."
                )
                result.finished_at = time.time()
                return result

            decision = self._policy.authorize(
                sd["tool_name"], validated, source=source, intent=intent
            )

            approval = ApprovalResult(
                step_index=idx,
                tool_name=sd["tool_name"],
                allowed=decision.kind not in (DecisionKind.DENY,),
                reason=decision.reason,
                risk=decision.risk.value,
            )

            if decision.kind == DecisionKind.DENY:
                result.approval_results.append(approval)
                result.mark_failed(
                    f"Step {idx + 1} ({sd['tool_name']}): denied by safety policy: {decision.reason}"
                )
                result.finished_at = time.time()
                return result

            result.approval_results.append(approval)

            step_result = self._execute_step(sd["tool_name"], validated, None)
            step_result.step_index = idx
            result.step_results.append(step_result)

            if not step_result.ok:
                result.ok = False
                result.error = step_result.message or "Step failed"
                result.finished_at = time.time()
                return result

        result.ok = True
        result.finished_at = time.time()
        return result

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _prepare_step_args(
        self,
        candidate: WorkflowCandidate,
        step_index: int,
        parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Prepare step arguments by substituting parameters from the candidate's slots."""
        step = candidate.steps[step_index]
        template = self._build_step_template(candidate, step_index)
        if template is None:
            return None
        return _substitute_template(template, parameters)

    def _build_step_template(
        self, candidate: WorkflowCandidate, step_index: int
    ) -> dict[str, Any] | None:
        """Build an argument template for a step, mapping slots to arg keys."""
        step = candidate.steps[step_index]
        template: dict[str, Any] = {}

        # Map each arg key to its slot name
        slot_key_map: dict[str, str] = {}
        for slot in candidate.parameter_slots:
            for key, value in step.args.items():
                slot_name = self._slot_name_for_arg(step, key)
                if slot_name == slot.name:
                    slot_key_map[key] = slot_name
                    template[key] = {"_slot": slot_name, "_type": slot.slot_type}
                    break

        # For args not mapped to slots, keep original value
        for key, value in step.args.items():
            if key not in template:
                template[key] = value

        return template

    @staticmethod
    def _slot_name_for_arg(step: WorkflowStep, arg_key: str) -> str:
        """Find the slot name for an arg key within a step."""
        name = arg_key.lower().strip()
        name = re.sub(r'[-_.\s]+', '_', name)
        name = re.sub(r'[^a-z0-9_]', '', name).strip('_')
        return name or "param"

    def _execute_step(
        self,
        tool_name: str,
        args: dict[str, Any],
        started_at: float | None,
    ) -> StepExecutionResult:
        """Execute a single step using a registered handler or shell_exec."""
        handler_started = time.monotonic()

        try:
            handler = self._handlers.get(tool_name)
            if handler is None:
                # Default: try to use the step's original handler
                return StepExecutionResult(
                    step_index=0,
                    tool_name=tool_name,
                    ok=False,
                    message=f"No handler registered for '{tool_name}'. Register it with executor.register_handler() first.",
                    started_at=started_at or 0.0,
                    finished_at=time.monotonic(),
                )
            result = handler(args)
            if hasattr(result, 'ok'):
                return StepExecutionResult(
                    step_index=0,
                    tool_name=tool_name,
                    ok=result.ok,
                    message=getattr(result, 'message', ''),
                    data=getattr(result, 'data', None),
                    started_at=started_at or 0.0,
                    finished_at=time.monotonic(),
                )
            return StepExecutionResult(
                step_index=0,
                tool_name=tool_name,
                ok=True,
                message=str(result) if result else "",
                data=result if isinstance(result, dict) else None,
                started_at=started_at or 0.0,
                finished_at=time.monotonic(),
            )
        except Exception as exc:
            return StepExecutionResult(
                step_index=0,
                tool_name=tool_name,
                ok=False,
                message=str(exc),
                started_at=started_at or 0.0,
                finished_at=time.monotonic(),
            )
