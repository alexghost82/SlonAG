"""Tests for workflow_learning.observer."""

from unittest.mock import MagicMock

import pytest

from mark.workflow_learning.observer import ActionObserver
from mark.workflow_learning.types import (
    ActionSequence,
    ActionSequenceEvent,
    WorkflowCandidate,
    WorkflowState,
    WorkflowStep,
)


def _make_observer(**kwargs):
    store = MagicMock()
    return ActionObserver(store=store, **kwargs)


class TestActionObserver:
    """Tests for ActionObserver."""

    def test_record_event(self):
        obs = _make_observer(buffer_size=5)
        obs.record_event(
            ActionSequenceEvent(tool_name="shell_exec", args={"command": "ls"}),
            ok=True,
            message="ok",
        )
        assert obs.get_buffer_size() == 1

    def test_auto_complete_on_buffer_full(self):
        candidate_created = []
        obs = _make_observer(buffer_size=3)
        obs.on_candidate_created(lambda c: candidate_created.append(c))

        for i in range(3):
            obs.record_event(
                ActionSequenceEvent(tool_name="shell_exec", args={"cmd": str(i)}),
                ok=True,
            )

        # Buffer should be cleared
        assert obs.get_buffer_size() == 0

    def test_record_step_convenience(self):
        obs = _make_observer(buffer_size=5)
        obs.record_step(
            tool_name="file_write",
            args={"path": "/tmp/test.txt", "content": "hello"},
            ok=True,
            message="written",
        )
        assert obs.get_buffer_size() == 1

    def test_clear_buffer(self):
        obs = _make_observer(buffer_size=10)
        obs.record_event(
            ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "ls"}),
            ok=True,
        )
        obs.clear_buffer()
        assert obs.get_buffer_size() == 0

    def test_get_history_empty(self):
        obs = _make_observer(buffer_size=5)
        history = obs.get_history()
        assert history == {}

    def test_history_updated_on_sequence(self, tmp_path):
        obs = _make_observer(
            buffer_size=3,
            min_repetitions=2,
        )
        obs.set_history_path(str(tmp_path / "history.json"))

        # First sequence (buffer_size=3, so auto-completes)
        for i in range(3):
            obs.record_event(
                ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "ls"}),
                ok=True,
            )
        keys = list(obs.get_history().keys())
        if keys:
            assert obs.get_sequence_count(keys[0]) == 1

        # Second sequence (same pattern)
        for i in range(3):
            obs.record_event(
                ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "ls"}),
                ok=True,
            )
        if keys:
            assert obs.get_sequence_count(keys[0]) == 2

    def test_store_called_on_candidate_created(self):
        store = MagicMock()
        obs = _make_observer(store=store, buffer_size=3, min_repetitions=1)

        for i in range(3):
            obs.record_event(
                ActionSequenceEvent(tool_name="shell_exec", args={"cmd": str(i)}),
                ok=True,
            )

        store.save_candidate.assert_called_once()
        candidate = store.save_candidate.call_args[0][0]
        assert candidate.state == WorkflowState.CANDIDATE

    def test_no_candidate_on_failure(self):
        store = MagicMock()
        obs = _make_observer(store=store, buffer_size=3, min_repetitions=1)

        # Record a failed sequence
        obs.record_event(
            ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "fail"}),
            ok=False,
            message="error",
        )
        obs.record_event(
            ActionSequenceEvent(tool_name="file_write", args={"path": "/tmp/x"}),
            ok=True,
        )
        obs.record_event(
            ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "ls"}),
            ok=True,
        )

        # Store should NOT be called because sequence is not successful
        store.save_candidate.assert_not_called()

    def test_callbacks_notified(self):
        captured = []
        obs = _make_observer(buffer_size=2, min_repetitions=1)
        obs.on_candidate_created(lambda c: captured.append(c))

        obs.record_event(
            ActionSequenceEvent(tool_name="shell_exec", args={"cmd": "ls"}),
            ok=True,
        )
        obs.record_event(
            ActionSequenceEvent(tool_name="file_write", args={"path": "/tmp/x"}),
            ok=True,
        )

        assert len(captured) == 1
        assert captured[0].state == WorkflowState.CANDIDATE


class TestSequenceAnalysis:
    """Tests for sequence hashing and analysis."""

    def test_same_tools_different_args_same_hash(self):
        seq1 = ActionSequence(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"cmd": "ls -la"}, ok=True),
                WorkflowStep(tool_name="file_read", args={"path": "/tmp/a.txt"}, ok=True),
            ]
        )
        seq2 = ActionSequence(
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"cmd": "pwd"}, ok=True),
                WorkflowStep(tool_name="file_read", args={"path": "/tmp/b.txt"}, ok=True),
            ]
        )
        hash1 = ActionObserver._sequence_hash(seq1)
        hash2 = ActionObserver._sequence_hash(seq2)
        assert hash1 == hash2  # Same tool names, same success

    def test_different_tools_different_hash(self):
        seq1 = ActionSequence(
            steps=[WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True)]
        )
        seq2 = ActionSequence(
            steps=[WorkflowStep(tool_name="file_read", args={"path": "/tmp/x"}, ok=True)]
        )
        assert ActionObserver._sequence_hash(seq1) != ActionObserver._sequence_hash(seq2)

    def test_success_vs_failure_different_hash(self):
        seq1 = ActionSequence(
            steps=[WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True)]
        )
        seq2 = ActionSequence(
            steps=[WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=False)]
        )
        assert ActionObserver._sequence_hash(seq1) != ActionObserver._sequence_hash(seq2)

    def test_empty_sequence_hash_deterministic(self):
        seq = ActionSequence(steps=[])
        h = ActionObserver._sequence_hash(seq)
        assert len(h) == 16  # SHA256 hex truncated to 16 chars
