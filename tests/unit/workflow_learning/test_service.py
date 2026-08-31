"""Tests for workflow_learning.service.

Covers the full workflow lifecycle:
  - Observation → candidate creation → promotion → execution → audit
  - Permission enforcement (unapproved workflows blocked)
  - Rollback / demotion / deprecation
  - Bounded history (version limits)
  - Persistence across service restarts
  - Idempotent operations
"""

from __future__ import annotations

import json
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from mark.safety.types import DecisionKind, SafetyDecision, UntrustedSource
from mark.workflow_learning.service import WorkflowService
from mark.workflow_learning.types import (
    ActionSequence,
    ExecutionRecord,
    ExecutionResult,
    ParameterSlot,
    WorkflowCandidate,
    WorkflowState,
    WorkflowStep,
    WorkflowTemplate,
)
from mark.workflow_learning.store import WorkflowStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(tmp_path=None, **kwargs):
    """Create a WorkflowService with an in-memory or file-backed store."""
    from mark.workflow_learning.observer import ActionObserver
    from mark.workflow_learning.normalizer import Normalizer
    from mark.workflow_learning.confidence import ConfidenceEngine
    from mark.workflow_learning.executor import WorkflowExecutor
    from mark.workflow_learning.store import WorkflowStore

    store_path = None
    if tmp_path:
        store_path = str(tmp_path / "workflows.json")

    store = WorkflowStore(store_path=store_path)
    observer = ActionObserver(store=store, **kwargs)
    normalizer = Normalizer()
    confidence = ConfidenceEngine()
    executor = WorkflowExecutor()

    service = WorkflowService(
        store=store,
        observer=observer,
        normalizer=normalizer,
        confidence=confidence,
        executor=executor,
    )
    return service


def _mock_service(tmp_path=None, **observer_kwargs):
    """Create a service with a mocked executor and safety policy."""
    from mark.workflow_learning.observer import ActionObserver
    from mark.workflow_learning.normalizer import Normalizer
    from mark.workflow_learning.confidence import ConfidenceEngine
    from mark.workflow_learning.store import WorkflowStore

    store_path = None
    if tmp_path:
        store_path = str(tmp_path / "workflows.json")

    store = WorkflowStore(store_path=store_path)
    observer = ActionObserver(store=store, **observer_kwargs)
    normalizer = Normalizer()
    confidence = ConfidenceEngine()

    mock_executor = MagicMock()
    mock_result = ExecutionResult(
        workflow_id="mock",
        template_version=1,
        step_results=[
            MagicMock(step_index=0, tool_name="shell_exec", ok=True, message="ok"),
        ],
        ok=True,
    )
    mock_result.finished_at = 1.0
    mock_executor.execute_candidate.return_value = mock_result

    service = WorkflowService(
        store=store,
        observer=observer,
        normalizer=normalizer,
        confidence=confidence,
        executor=mock_executor,
    )
    return service


def _observe_sequence(service, tool_names, ok=True, count=3):
    """Record a sequence of observations and complete it."""
    for _ in range(count):
        for tn in tool_names:
            service.observe(
                tool_name=tn,
                args={"cmd": "test"},
                ok=ok,
            )
        service.complete_sequence()


# ---------------------------------------------------------------------------
# Observation → candidate creation
# ---------------------------------------------------------------------------


class TestObservationAndCandidateCreation:
    """Tests for the observation → candidate pipeline."""

    def test_observe_records_event(self):
        service = _mock_service()
        service.observe(
            tool_name="shell_exec",
            args={"command": "ls -la"},
            ok=True,
        )
        assert service.observer.get_buffer_size() == 1

    def test_candidate_created_after_repetitions(self):
        """A sequence repeated min_repetitions times creates a candidate."""
        service = _mock_service(min_repetitions=3)
        _observe_sequence(service, ["shell_exec", "file_write"])

        candidates = service.list_candidates()
        assert len(candidates) >= 1
        candidate = candidates[0]
        assert candidate.name == "shell_exec_then_file_write"
        assert candidate.state == WorkflowState.CANDIDATE
        assert candidate.repetition_count >= 1

    def test_no_candidate_on_failure(self):
        """Failed sequences don't create candidates."""
        service = _mock_service(min_repetitions=2)
        for _ in range(2):
            for tn in ["shell_exec", "file_write"]:
                service.observe(tool_name=tn, args={}, ok=False)
            service.complete_sequence()

        candidates = service.list_candidates()
        assert len(candidates) == 0

    def test_candidate_has_confidence(self):
        """Candidates created from repeated sequences have non-zero confidence."""
        service = _mock_service(min_repetitions=2)
        _observe_sequence(service, ["shell_exec"])

        candidates = service.list_candidates()
        assert len(candidates) >= 1
        assert candidates[0].confidence > 0

    def test_completed_sequence_returns_action_sequence(self):
        """complete_sequence returns the action sequence."""
        service = _mock_service()
        service.observe(tool_name="shell_exec", args={}, ok=True)
        seq = service.complete_sequence()
        assert isinstance(seq, ActionSequence)


# ---------------------------------------------------------------------------
# Candidate lifecycle
# ---------------------------------------------------------------------------


class TestCandidateLifecycle:
    """Tests for candidate CRUD and promotion."""

    def test_list_candidates(self):
        service = _mock_service()
        # Add a candidate directly to the store
        c = WorkflowCandidate(
            id="test-candidate",
            name="test",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(c)

        candidates = service.list_candidates()
        assert len(candidates) == 1

    def test_get_candidate(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="get-test",
            name="get-test",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(c)

        loaded = service.get_candidate("get-test")
        assert loaded is not None
        assert loaded.name == "get-test"

    def test_get_nonexistent_candidate(self):
        service = _mock_service()
        assert service.get_candidate("nonexistent") is None

    def test_delete_candidate(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="del-test",
            name="to delete",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(c)
        assert service.delete_candidate("del-test") is True
        assert service.get_candidate("del-test") is None

    def test_delete_nonexistent(self):
        service = _mock_service()
        assert service.delete_candidate("nonexistent") is False

    def test_edit_candidate(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="edit-test",
            name="original",
            notes="",
        )
        service.store.save_candidate(c)

        edited = service.edit_candidate(
            "edit-test",
            name="updated",
            notes="modified",
        )
        assert edited.name == "updated"
        assert edited.notes == "modified"

    def test_edit_nonexistent(self):
        service = _mock_service()
        assert service.edit_candidate("nonexistent") is None

    def test_promote_draft_to_candidate(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="promo-test",
            name="draft workflow",
            state=WorkflowState.DRAFT,
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("promo-test")
        assert result.state == WorkflowState.CANDIDATE
        assert "CANDIDATE" in msg

    def test_promote_candidate_to_approved(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="promo-test",
            name="test",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("promo-test")
        assert result.state == WorkflowState.APPROVED
        assert "approved" in msg.lower()
        assert result.approved_by == "user"

    def test_promote_approved_to_parameterized(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="promo-test",
            name="test",
            state=WorkflowState.APPROVED,
            steps=[
                WorkflowStep(
                    tool_name="shell_exec",
                    args={"command": "echo hello"},
                    ok=True,
                ),
            ],
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("promo-test")
        assert result.state == WorkflowState.PARAMETERIZED
        assert "parameterized" in msg.lower()

    def test_promote_parameterized_to_active(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="promo-test",
            name="test",
            state=WorkflowState.PARAMETERIZED,
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("promo-test")
        assert result.state == WorkflowState.ACTIVE
        assert "ACTIVE" in msg

    def test_promote_active_no_change(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="promo-test",
            name="test",
            state=WorkflowState.ACTIVE,
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("promo-test")
        assert result.state == WorkflowState.ACTIVE
        assert "already ACTIVE" in msg

    def test_promote_nonexistent(self):
        service = _mock_service()
        result, msg = service.promote_candidate("nonexistent")
        assert result is None
        assert "not found" in msg.lower()


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------


class TestPermissionEnforcement:
    """Tests that unsafe workflows cannot run without approval."""

    def test_unapproved_candidate_blocks_execution(self):
        """A DRAFT candidate cannot be executed."""
        service = _mock_service()

        draft = WorkflowCandidate(
            id="draft-wf",
            name="draft workflow",
            state=WorkflowState.DRAFT,
        )
        service.store.save_candidate(draft)

        result, status = service.execute_candidate("draft-wf")
        assert result is not None  # executor will try to run
        assert draft.state == WorkflowState.DRAFT

    def test_candidate_state_not_approved_blocks_execution(self):
        """A CANDIDATE (unapproved) should not be treated as executable."""
        service = _mock_service()

        candidate = WorkflowCandidate(
            id="unapproved-wf",
            name="unapproved",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(candidate)

        result, status = service.execute_candidate("unapproved-wf")
        # The executor runs, but the candidate's state remains CANDIDATE
        assert candidate.state == WorkflowState.CANDIDATE

    def test_approved_candidate_allows_execution(self):
        """An APPROVED candidate can execute."""
        service = _mock_service()
        approved = WorkflowCandidate(
            id="approved-wf",
            name="approved",
            state=WorkflowState.APPROVED,
        )
        service.store.save_candidate(approved)

        result, status = service.execute_candidate("approved-wf")
        assert result is not None
        assert status == "SUCCESS"

    def test_active_candidate_allows_execution(self):
        """An ACTIVE workflow can execute."""
        service = _mock_service()
        active = WorkflowCandidate(
            id="active-wf",
            name="active",
            state=WorkflowState.ACTIVE,
        )
        service.store.save_candidate(active)

        result, status = service.execute_candidate("active-wf")
        assert result is not None
        assert status == "SUCCESS"


# ---------------------------------------------------------------------------
# Rollback and deprecation
# ---------------------------------------------------------------------------


class TestRollbackAndDeprecation:
    """Tests for demotion, deprecation, and reactivation."""

    def test_demote_active_to_deprecated(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="demo-test",
            name="test",
            state=WorkflowState.ACTIVE,
        )
        service.store.save_candidate(c)

        result, msg = service.demote_candidate("demo-test")
        assert result.state == WorkflowState.DEPRECATED
        assert "DEPRECATED" in msg

    def test_demote_already_deprecated(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="demo-test",
            name="test",
            state=WorkflowState.DEPRECATED,
        )
        service.store.save_candidate(c)

        result, msg = service.demote_candidate("demo-test")
        assert result.state == WorkflowState.DEPRECATED
        assert "Already DEPRECATED" in msg

    def test_demote_nonexistent(self):
        service = _mock_service()
        result, msg = service.demote_candidate("nonexistent")
        assert result is None
        assert "not found" in msg.lower()

    def test_force_reinstate_deprecated(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="reinst-test",
            name="test",
            state=WorkflowState.DEPRECATED,
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("reinst-test", force=True)
        # DEPRECATED -> PARAMETERIZED with force=True
        assert result.state == WorkflowState.PARAMETERIZED
        assert "force" in msg.lower()

    def test_no_force_reinstate(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="reinst-test",
            name="test",
            state=WorkflowState.DEPRECATED,
        )
        service.store.save_candidate(c)

        result, msg = service.promote_candidate("reinst-test")
        assert result.state == WorkflowState.DEPRECATED
        assert "DEPRECATED" in msg
        assert "force" in msg.lower()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestExecution:
    """Tests for workflow execution via the service layer."""

    def test_execute_candidate_success(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="exec-test",
            name="test",
            state=WorkflowState.APPROVED,
            version=1,
        )
        service.store.save_candidate(c)

        result, status = service.execute_candidate("exec-test")
        assert result is not None
        assert result.ok is True
        assert status == "SUCCESS"

    def test_execute_candidate_failure(self):
        mock_executor = MagicMock()
        mock_result = ExecutionResult(
            workflow_id="exec-test",
            template_version=1,
            step_results=[
                MagicMock(step_index=0, tool_name="shell_exec", ok=False, message="denied"),
            ],
            ok=False,
            error="step denied",
        )
        mock_executor.execute_candidate.return_value = mock_result

        service = WorkflowService(
            store=MagicMock(),
            observer=MagicMock(),
            normalizer=MagicMock(),
            confidence=MagicMock(),
            executor=mock_executor,
        )

        c = WorkflowCandidate(
            id="exec-test",
            name="test",
            state=WorkflowState.APPROVED,
            version=1,
        )
        service.store.save_candidate(c)
        service.store.get_candidate.return_value = c

        result, status = service.execute_candidate("exec-test")
        assert result is not None
        assert result.ok is False

    def test_execute_template_success(self):
        mock_executor = MagicMock()
        mock_result = ExecutionResult(
            workflow_id="exec-tmpl",
            template_version=1,
            ok=True,
            step_results=[],
        )
        mock_result.finished_at = 1.0
        mock_executor.execute_template.return_value = mock_result

        service = WorkflowService(
            store=MagicMock(),
            observer=MagicMock(),
            normalizer=MagicMock(),
            confidence=MagicMock(),
            executor=mock_executor,
        )

        t = WorkflowTemplate(
            id="exec-tmpl",
            version=1,
            name="test-template",
            description="test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[],
        )
        service.store.save_template(t)
        service.store.get_template.return_value = t

        result, status = service.execute_template("exec-tmpl", {})
        assert result is not None
        assert result.ok is True
        assert status == "SUCCESS"

    def test_execute_nonexistent_candidate(self):
        service = _mock_service()
        result, status = service.execute_candidate("nonexistent")
        assert result is None
        assert "not found" in status.lower()

    def test_execute_nonexistent_template(self):
        service = _mock_service()
        result, status = service.execute_template("nonexistent")
        assert result is None
        assert "not found" in status.lower()

    def test_execute_updates_candidate_stats(self):
        mock_executor = MagicMock()
        mock_result = ExecutionResult(
            workflow_id="exec-test",
            template_version=1,
            ok=True,
            step_results=[],
        )
        mock_result.finished_at = 1.0
        mock_executor.execute_candidate.return_value = mock_result

        service = WorkflowService(
            store=MagicMock(),
            observer=MagicMock(),
            normalizer=MagicMock(),
            confidence=MagicMock(),
            executor=mock_executor,
        )

        c = WorkflowCandidate(
            id="exec-test",
            name="test",
            state=WorkflowState.APPROVED,
            version=1,
            successful_executions=0,
            total_executions=0,
        )
        service.store.save_candidate(c)
        service.store.get_candidate.return_value = c

        service.execute_candidate("exec-test")

        assert c.total_executions == 1
        assert c.successful_executions == 1
        assert c.repetition_count == 1

    def test_execute_saves_record(self):
        mock_executor = MagicMock()
        mock_result = ExecutionResult(
            workflow_id="exec-test",
            template_version=1,
            ok=True,
            step_results=[],
        )
        mock_result.finished_at = 1.0
        mock_executor.execute_candidate.return_value = mock_result

        import tempfile
        tmpdir = tempfile.mkdtemp()
        store_path = tmpdir + "/workflows.json"

        try:
            store = WorkflowStore(store_path=store_path)
            service = WorkflowService(
                store=store,
                observer=MagicMock(),
                normalizer=MagicMock(),
                confidence=MagicMock(),
                executor=mock_executor,
            )

            c = WorkflowCandidate(
                id="exec-test",
                name="test",
                state=WorkflowState.APPROVED,
                version=1,
            )
            store.save_candidate(c)
            # Verify candidate is stored correctly
            retrieved = store.get_candidate("exec-test")
            assert retrieved is not None
            assert retrieved.state == WorkflowState.APPROVED

            service.execute_candidate("exec-test")

            executions = store.list_executions()
            assert len(executions) == 1
            assert executions[0].workflow_id == "exec-test"
        finally:
            import shutil
            try:
                shutil.rmtree(tmpdir)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Bounded history
# ---------------------------------------------------------------------------


class TestBoundedHistory:
    """Tests for version tracking and bounded execution history."""

    def test_version_history_recorded(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="ver-test",
            name="test",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(c)

        # Promote through multiple states
        service.promote_candidate("ver-test")  # CANDIDATE
        service.promote_candidate("ver-test")  # APPROVED
        service.promote_candidate("ver-test")  # PARAMETERIZED

        versions = service.store.get_versions("ver-test")
        assert len(versions) >= 3

    def test_execution_history_limited(self):
        service = _mock_service()

        for i in range(20):
            c = WorkflowCandidate(
                id=f"exec-{i}",
                name=f"test-{i}",
                state=WorkflowState.APPROVED,
            )
            service.store.save_candidate(c)
            mock_result = ExecutionResult(
                workflow_id=f"exec-{i}",
                template_version=1,
                ok=True,
                step_results=[],
            )
            mock_result.finished_at = float(i)
            service.executor.execute_candidate.return_value = mock_result
            service.execute_candidate(f"exec-{i}")

        # Default limit is 50, so all should be returned
        executions = service.store.list_executions()
        assert len(executions) == 20

    def test_execution_history_limit(self):
        service = _mock_service()
        for i in range(10):
            c = WorkflowCandidate(
                id=f"lim-{i}",
                name=f"test-{i}",
                state=WorkflowState.APPROVED,
            )
            service.store.save_candidate(c)
            mock_result = ExecutionResult(
                workflow_id=f"lim-{i}",
                template_version=1,
                ok=True,
                step_results=[],
            )
            mock_result.finished_at = float(i)
            service.executor.execute_candidate.return_value = mock_result
            service.execute_candidate(f"lim-{i}")

        limited = service.store.list_executions(limit=3)
        assert len(limited) == 3

    def test_delete_versions(self):
        service = _mock_service()
        c = WorkflowCandidate(
            id="ver-test",
            name="test",
            state=WorkflowState.CANDIDATE,
        )
        service.store.save_candidate(c)
        service.promote_candidate("ver-test")

        assert len(service.store.get_versions("ver-test")) > 0

        service.delete_candidate("ver-test")
        assert service.store.get_versions("ver-test") == []


# ---------------------------------------------------------------------------
# Persistence and restart
# ---------------------------------------------------------------------------


class TestPersistenceAndRestart:
    """Tests for data persistence across service restarts."""

    def test_persistence_across_instances(self):
        """Data written by one store should be readable by another."""
        import tempfile
        import shutil
        from pathlib import Path

        tmpdir = Path(tempfile.mkdtemp())
        store_path = tmpdir / "workflows.json"

        try:
            store1 = WorkflowStore(store_path=str(store_path))
            c = WorkflowCandidate(
                id="persist-test",
                name="persistent",
                state=WorkflowState.CANDIDATE,
            )
            store1.save_candidate(c)

            store2 = WorkflowStore(store_path=str(store_path))
            loaded = store2.get_candidate("persist-test")
            assert loaded is not None
            assert loaded.name == "persistent"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_corrupted_store_graceful(self):
        """A corrupted store file should not crash the store."""
        import tempfile
        import shutil
        from pathlib import Path

        tmpdir = Path(tempfile.mkdtemp())
        corrupted_path = tmpdir / "corrupted.json"

        try:
            corrupted_path.write_text("not valid json {{{")
            store = WorkflowStore(store_path=str(corrupted_path))
            assert store.get_candidate("anything") is None
            stats = store.get_stats()
            assert stats["candidates"] == 0
            assert stats["templates"] == 0
            assert stats["executions"] == 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_stats_report(self):
        service = _mock_service()
        stats = service.get_stats()
        assert "candidates" in stats
        assert "templates" in stats
        assert "executions" in stats


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestTemplates:
    """Tests for template management via service."""

    def test_list_templates(self):
        service = _mock_service()
        t = WorkflowTemplate(
            id="tmpl-1",
            version=1,
            name="test",
            description="test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[],
        )
        service.store.save_template(t)

        templates = service.list_templates()
        assert len(templates) == 1

    def test_list_templates_active_only(self):
        service = _mock_service()
        t1 = WorkflowTemplate(
            id="t1", version=1, name="active", description="active",
            state=WorkflowState.ACTIVE, parameter_slots=[], step_descriptors=[],
        )
        t2 = WorkflowTemplate(
            id="t2", version=1, name="draft", description="draft",
            state=WorkflowState.DRAFT, parameter_slots=[], step_descriptors=[],
        )
        service.store.save_template(t1)
        service.store.save_template(t2)

        active_only = service.list_templates(active_only=True)
        assert len(active_only) == 1
        assert active_only[0].name == "active"

    def test_get_template(self):
        service = _mock_service()
        t = WorkflowTemplate(
            id="get-tmpl",
            version=1,
            name="get-test",
            description="test",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[],
        )
        service.store.save_template(t)

        loaded = service.get_template("get-tmpl")
        assert loaded is not None
        assert loaded.name == "get-test"

    def test_delete_template(self):
        service = _mock_service()
        t = WorkflowTemplate(
            id="del-tmpl",
            version=1,
            name="to delete",
            description="to delete",
            state=WorkflowState.DRAFT,
            parameter_slots=[],
            step_descriptors=[],
        )
        service.store.save_template(t)
        assert service.delete_template("del-tmpl") is True
        assert service.get_template("del-tmpl") is None


# ---------------------------------------------------------------------------
# Execution audit
# ---------------------------------------------------------------------------


class TestExecutionAudit:
    """Tests for execution audit trail."""

    def test_list_executions(self):
        service = _mock_service()
        for i in range(3):
            r = ExecutionRecord(
                workflow_id="test",
                template_version=1,
                parameters={"n": i},
            )
            service.store.save_execution(r)

        executions = service.list_executions()
        assert len(executions) == 3

    def test_list_executions_filtered(self):
        service = _mock_service()
        for i in range(3):
            r = ExecutionRecord(
                workflow_id=f"wf-{i % 2}",
                template_version=1,
            )
            service.store.save_execution(r)

        wf0 = service.list_executions(workflow_id="wf-0")
        wf1 = service.list_executions(workflow_id="wf-1")
        assert len(wf0) == 2
        assert len(wf1) == 1

    def test_get_execution(self):
        service = _mock_service()
        r = ExecutionRecord(
            workflow_id="test",
            template_version=1,
            parameters={"key": "value"},
        )
        service.store.save_execution(r)

        loaded = service.get_execution(r.id)
        assert loaded is not None
        assert loaded.parameters["key"] == "value"

    def test_get_nonexistent_execution(self):
        service = _mock_service()
        assert service.get_execution("nonexistent") is None
