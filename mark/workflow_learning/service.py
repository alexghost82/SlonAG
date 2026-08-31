"""High-level service layer for workflow learning.

Provides the unified API:
  - observe() – feed tool execution results
  - list_candidates() / get_candidate() / delete_candidate()
  - promote() – move candidate -> approved -> parameterized -> active
  - edit_candidate() – update name, description, notes
  - execute_candidate() / execute_template() – run workflows
  - list_templates() / get_template() / delete_template()
  - list_executions() – audit trail

All state transitions go through the service with validation.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from mark.safety.types import UntrustedSource
from mark.workflow_learning.types import (
    ActionSequence,
    ActionSequenceEvent,
    ExecutionRecord,
    ExecutionResult,
    ParameterSlot,
    WorkflowCandidate,
    WorkflowState,
    WorkflowTemplate,
)


class WorkflowService:
    """Unified service for all workflow learning operations."""

    def __init__(
        self,
        store: Any,
        observer: Any,
        normalizer: Any,
        confidence: Any,
        executor: Any,
    ) -> None:
        self.store = store
        self.observer = observer
        self.normalizer = normalizer
        self.confidence = confidence
        self.executor = executor

        # Link observer to store for persistence
        self.observer.set_store(store)

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        ok: bool,
        message: str = "",
        data: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
        session_id: str | None = None,
        intent: str = "",
    ) -> ActionSequence | None:
        """Record a single tool execution in the observation stream."""
        self.observer.record_step(
            tool_name=tool_name,
            args=args,
            ok=ok,
            message=message,
            data=data,
            tool_call_id=tool_call_id,
        )
        return None

    def complete_sequence(
        self,
        session_id: str | None = None,
        intent: str = "",
    ) -> ActionSequence | None:
        """Signal that a sequence of observations is complete.

        Triggers candidate creation if the observed pattern repeats enough.
        Returns the sequence if a new candidate was created.
        """
        return self.observer.mark_complete()

    # ------------------------------------------------------------------
    # Candidate lifecycle
    # ------------------------------------------------------------------

    def list_candidates(
        self,
        *,
        state: WorkflowState | None = None,
        active_only: bool = False,
    ) -> list[WorkflowCandidate]:
        """List workflow candidates."""
        candidates = self.store.list_candidates(state=state, active_only=active_only)
        # Update confidence scores
        for c in candidates:
            self.confidence.update(c)
        return candidates

    def get_candidate(self, candidate_id: str) -> WorkflowCandidate | None:
        """Get a candidate by ID."""
        c = self.store.get_candidate(candidate_id)
        if c is not None:
            self.confidence.update(c)
        return c

    def delete_candidate(self, candidate_id: str) -> bool:
        """Delete a candidate and all its versions."""
        self.store.delete_versions(candidate_id)
        return self.store.delete_candidate(candidate_id)

    def edit_candidate(
        self,
        candidate_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        notes: str | None = None,
    ) -> WorkflowCandidate | None:
        """Edit a candidate's metadata."""
        c = self.store.get_candidate(candidate_id)
        if c is None:
            return None
        if name is not None:
            c.name = name
        if description is not None:
            c.description = description
        if notes is not None:
            c.notes = notes
        self.store.save_candidate(c)
        return c

    # ------------------------------------------------------------------
    # Promotion pipeline
    # ------------------------------------------------------------------

    def promote_candidate(
        self,
        candidate_id: str,
        *,
        force: bool = False,
    ) -> tuple[WorkflowCandidate | None, str]:
        """Promote a candidate through its lifecycle.

        Returns (candidate, message).
        States: DRAFT -> CANDIDATE -> APPROVED -> PARAMETERIZED -> ACTIVE
        """
        c = self.store.get_candidate(candidate_id)
        if c is None:
            return None, "Candidate not found."

        if c.state == WorkflowState.DRAFT:
            c.transition_to(WorkflowState.CANDIDATE)
            self.confidence.update(c)
            self.store.save_candidate(c)
            return c, f"Moved to CANDIDATE state."

        elif c.state == WorkflowState.CANDIDATE:
            c.transition_to(WorkflowState.APPROVED)
            c.approved_by = "user"
            self.confidence.update(c)
            self.store.save_candidate(c)
            return c, "Candidate approved."

        elif c.state == WorkflowState.APPROVED:
            # Extract parameter slots and create template
            self._parameterize_candidate(c)
            c.transition_to(WorkflowState.PARAMETERIZED)
            self.store.save_candidate(c)
            self.store.save_template(self._build_template(c))
            return c, "Parameterized and template created."

        elif c.state == WorkflowState.PARAMETERIZED:
            c.transition_to(WorkflowState.ACTIVE)
            self.store.save_candidate(c)
            return c, "Workflow is now ACTIVE."

        elif c.state == WorkflowState.ACTIVE:
            return c, "Workflow is already ACTIVE."

        elif c.state == WorkflowState.DEPRECATED:
            if force:
                c.transition_to(WorkflowState.PARAMETERIZED)
                self.store.save_candidate(c)
                return c, "Deprecated workflow reinstated to PARAMETERIZED (force). Re-promote to ACTIVE when ready."
            return c, "Workflow is DEPRECATED. Use force=True to reinstate."

        return c, f"Unexpected state: {c.state}"

    def demote_candidate(
        self,
        candidate_id: str,
    ) -> tuple[WorkflowCandidate | None, str]:
        """Demote a candidate to DEPRECATED."""
        c = self.store.get_candidate(candidate_id)
        if c is None:
            return None, "Candidate not found."

        if c.state != WorkflowState.DEPRECATED:
            c.transition_to(WorkflowState.DEPRECATED)
            self.store.save_candidate(c)
            return c, "Workflow is now DEPRECATED."
        return c, "Already DEPRECATED."

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_candidate(
        self,
        candidate_id: str,
        parameters: dict[str, Any] | None = None,
        *,
        source: UntrustedSource = UntrustedSource.USER,
        intent: str = "",
    ) -> tuple[ExecutionResult | None, str]:
        """Execute a workflow candidate by ID."""
        c = self.store.get_candidate(candidate_id)
        if c is None:
            return None, "Candidate not found."

        params = parameters or {}
        result = self.executor.execute_candidate(c, params, source=source, intent=intent)

        # Save execution record
        record = ExecutionRecord(
            workflow_id=candidate_id,
            template_version=c.version,
            parameters=params,
            result=result,
        )
        self.store.save_execution(record)

        # Update candidate stats
        c.total_executions += 1
        if result.ok:
            c.successful_executions += 1
            c.repetition_count += 1
        self.confidence.update(c)
        self.store.save_candidate(c)

        status = "SUCCESS" if result.ok else f"FAILED: {result.error or result.step_results[-1].message if result.step_results else 'unknown'}"
        return result, status

    def execute_template(
        self,
        template_id: str,
        parameters: dict[str, Any] | None = None,
        *,
        source: UntrustedSource = UntrustedSource.USER,
        intent: str = "",
    ) -> tuple[ExecutionResult | None, str]:
        """Execute a workflow template by ID."""
        t = self.store.get_template(template_id)
        if t is None:
            return None, "Template not found."

        params = parameters or {}
        result = self.executor.execute_template(t, params, source=source, intent=intent)

        record = ExecutionRecord(
            workflow_id=t.id,
            template_version=t.version,
            parameters=params,
            result=result,
        )
        self.store.save_execution(record)

        status = "SUCCESS" if result.ok else f"FAILED: {result.error}"
        return result, status

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def list_templates(self, *, active_only: bool = False) -> list[WorkflowTemplate]:
        """List workflow templates."""
        return self.store.list_templates(active_only=active_only)

    def get_template(self, template_id: str) -> WorkflowTemplate | None:
        """Get a template by ID."""
        return self.store.get_template(template_id)

    def delete_template(self, template_id: str) -> bool:
        """Delete a template."""
        return self.store.delete_template(template_id)

    # ------------------------------------------------------------------
    # Executions / audit
    # ------------------------------------------------------------------

    def list_executions(
        self,
        workflow_id: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionRecord]:
        """List execution records."""
        return self.store.list_executions(workflow_id=workflow_id, limit=limit)

    def get_execution(self, record_id: str) -> ExecutionRecord | None:
        """Get an execution record by ID."""
        return self.store.get_execution(record_id)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return overall service statistics."""
        return self.store.get_stats()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parameterize_candidate(self, candidate: WorkflowCandidate) -> None:
        """Extract parameter slots from a candidate's steps."""
        all_slots: dict[str, ParameterSlot] = {}
        for idx, step in enumerate(candidate.steps):
            slots = self.normalizer.extract_slots(step)
            for slot in slots:
                if slot.name not in all_slots:
                    all_slots[slot.name] = slot

        candidate.parameter_slots = list(all_slots.values())

    def _build_template(
        self, candidate: WorkflowCandidate
    ) -> WorkflowTemplate:
        """Build a WorkflowTemplate from a parameterized candidate."""
        import json
        step_descriptors = []
        for idx, step in enumerate(candidate.steps):
            # Build arg template from slots
            arg_template: dict[str, Any] = {}
            for key, value in step.args.items():
                slot_name = self.normalizer._key_to_slot_name(key)
                slot = next(
                    (s for s in candidate.parameter_slots if s.name == slot_name),
                    None,
                )
                if slot:
                    arg_template[key] = {
                        "_slot": slot.name,
                        "_type": slot.slot_type,
                    }
                else:
                    arg_template[key] = value

            required_slots = [
                s.name for s in candidate.parameter_slots
                if any(self.normalizer._key_to_slot_name(k) == s.name for k in step.args)
            ]

            step_descriptors.append({
                "tool_name": step.tool_name,
                "arg_template": arg_template,
                "required_slots": required_slots,
                "safety_risk": 0,  # Filled at runtime by risk_for()
            })

        return WorkflowTemplate(
            id=candidate.id,
            version=candidate.version,
            name=candidate.name,
            description=candidate.description,
            state=candidate.state,
            parameter_slots=candidate.parameter_slots,
            step_descriptors=step_descriptors,
            created_at=candidate.created_at,
            updated_at=time.time(),
        )
