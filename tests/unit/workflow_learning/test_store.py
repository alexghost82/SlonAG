"""Tests for workflow_learning.store."""

import json
from pathlib import Path

import pytest

from acta.workflow_learning.store import WorkflowStore
from acta.workflow_learning.types import (
    ExecutionRecord,
    WorkflowCandidate,
    WorkflowState,
    WorkflowTemplate,
    WorkflowStep,
)


class TestWorkflowStore:
    """Tests for WorkflowStore persistence."""

    def test_initial_data_structure(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "workflows.json")
        data = json.loads((tmp_path / "workflows.json").read_text())
        assert "candidates" in data
        assert "templates" in data
        assert "versions" in data
        assert "executions" in data
        assert "metadata" in data
        assert data["metadata"]["schema_version"] == "1.0"

    def test_save_and_get_candidate(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        c = WorkflowCandidate(
            id="test-candidate",
            name="test workflow",
            state=WorkflowState.CANDIDATE,
        )
        store.save_candidate(c)
        loaded = store.get_candidate("test-candidate")
        assert loaded is not None
        assert loaded.name == "test workflow"
        assert loaded.state == WorkflowState.CANDIDATE

    def test_get_nonexistent_candidate(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        assert store.get_candidate("nonexistent") is None

    def test_list_candidates(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        c1 = WorkflowCandidate(id="c1", name="first", state=WorkflowState.CANDIDATE)
        c2 = WorkflowCandidate(id="c2", name="second", state=WorkflowState.APPROVED)
        store.save_candidate(c1)
        store.save_candidate(c2)

        all_c = store.list_candidates()
        assert len(all_c) == 2

        approved = store.list_candidates(state=WorkflowState.APPROVED)
        assert len(approved) == 1
        assert approved[0].id == "c2"

    def test_delete_candidate(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        c = WorkflowCandidate(id="del-candidate", name="to delete", state=WorkflowState.CANDIDATE)
        store.save_candidate(c)
        assert store.get_candidate("del-candidate") is not None

        assert store.delete_candidate("del-candidate") is True
        assert store.get_candidate("del-candidate") is None

    def test_delete_nonexistent(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        assert store.delete_candidate("nonexistent") is False

    def test_save_and_get_template(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        t = WorkflowTemplate(
            id="tmpl-1",
            version=1,
            name="test-template",
            description="A test template",
            state=WorkflowState.ACTIVE,
            parameter_slots=[],
            step_descriptors=[],
        )
        store.save_template(t)
        loaded = store.get_template("tmpl-1")
        assert loaded is not None
        assert loaded.name == "test-template"

    def test_list_templates(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        t1 = WorkflowTemplate(id="t1", version=1, name="active", description="active", state=WorkflowState.ACTIVE,
                              parameter_slots=[], step_descriptors=[])
        t2 = WorkflowTemplate(id="t2", version=1, name="draft", description="draft", state=WorkflowState.DRAFT,
                              parameter_slots=[], step_descriptors=[])
        store.save_template(t1)
        store.save_template(t2)

        active = store.list_templates(active_only=True)
        assert len(active) == 1
        assert active[0].name == "active"

    def test_delete_template(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        t = WorkflowTemplate(id="del-tmpl", version=1, name="to delete", description="to delete",
                             state=WorkflowState.DRAFT, parameter_slots=[], step_descriptors=[])
        store.save_template(t)
        assert store.delete_template("del-tmpl") is True
        assert store.get_template("del-tmpl") is None

    def test_save_and_get_execution(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        r = ExecutionRecord(
            workflow_id="test-workflow",
            template_version=1,
            parameters={"filename": "/tmp/x.txt", "count": 5},
        )
        store.save_execution(r)

        loaded = store.get_execution(r.id)
        assert loaded is not None
        assert loaded.workflow_id == "test-workflow"
        assert loaded.parameters["filename"] == "/tmp/x.txt"

    def test_list_executions(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        for i in range(3):
            r = ExecutionRecord(workflow_id="test", template_version=1, parameters={"n": i})
            store.save_execution(r)

        all_ex = store.list_executions()
        assert len(all_ex) == 3

        filtered = store.list_executions(workflow_id="test")
        assert len(filtered) == 3

    def test_limit_executions(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        for i in range(10):
            r = ExecutionRecord(workflow_id="test", template_version=1)
            store.save_execution(r)
        limited = store.list_executions(limit=3)
        assert len(limited) == 3

    def test_record_version(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        store.record_version("test-candidate", version=1, state=WorkflowState.CANDIDATE)
        versions = store.get_versions("test-candidate")
        assert len(versions) == 1
        assert versions[0]["version"] == 1
        assert versions[0]["state"] == "candidate"

    def test_get_versions_nonexistent(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        assert store.get_versions("nonexistent") == []

    def test_delete_versions(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        store.record_version("test", version=1, state=WorkflowState.CANDIDATE)
        assert store.delete_versions("test") is True
        assert store.delete_versions("nonexistent") is False
        assert store.get_versions("test") == []

    def test_get_stats(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        stats = store.get_stats()
        assert stats["candidates"] == 0
        assert stats["templates"] == 0
        assert stats["executions"] == 0
        assert stats["schema_version"] == "1.0"

    def test_persistence_across_instances(self, tmp_path):
        """Data written by one instance should be readable by another."""
        store1 = WorkflowStore(store_path=tmp_path / "wf.json")
        c = WorkflowCandidate(id="persist-candidate", name="persistent", state=WorkflowState.CANDIDATE)
        store1.save_candidate(c)

        store2 = WorkflowStore(store_path=tmp_path / "wf.json")
        loaded = store2.get_candidate("persist-candidate")
        assert loaded is not None
        assert loaded.name == "persistent"

    def test_corrupted_file_graceful(self, tmp_path):
        store_path = tmp_path / "wf.json"
        store_path.write_text("not valid json {{{")
        store = WorkflowStore(store_path=store_path)
        assert store.get_candidate("anything") is None
        assert store.get_stats()["candidates"] == 0

    def test_version_record_in_data(self, tmp_path):
        store = WorkflowStore(store_path=tmp_path / "wf.json")
        c = WorkflowCandidate(id="ver-candidate", name="versioned", state=WorkflowState.CANDIDATE)
        store.save_candidate(c)
        versions = store.get_versions("ver-candidate")
        assert len(versions) >= 1
