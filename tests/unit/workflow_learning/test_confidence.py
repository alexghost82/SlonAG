"""Tests for workflow_learning.confidence."""

import pytest

from mark.workflow_learning.confidence import ConfidenceEngine
from mark.workflow_learning.types import WorkflowCandidate, WorkflowState, WorkflowStep


class TestConfidenceEngine:
    """Tests for ConfidenceEngine."""

    def test_new_candidate_has_zero_confidence(self):
        engine = ConfidenceEngine()
        c = WorkflowCandidate(name="test", steps=[])
        score = engine.compute(c)
        assert score == 0.0

    def test_single_step_no_repetitions(self):
        engine = ConfidenceEngine()
        c = WorkflowCandidate(
            name="test",
            steps=[WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True)],
            repetition_count=1,
        )
        score = engine.compute(c)
        assert 0.0 <= score <= 1.0

    def test_high_repetitions(self):
        engine = ConfidenceEngine()
        c = WorkflowCandidate(
            name="test",
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True),
                WorkflowStep(tool_name="file_write", args={"path": "/tmp/x"}, ok=True),
            ],
            repetition_count=20,
        )
        score = engine.compute(c)
        assert score > 0.5

    def test_update_mutates_candidate(self):
        engine = ConfidenceEngine()
        c = WorkflowCandidate(
            name="test",
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True),
            ],
            repetition_count=10,
        )
        engine.update(c)
        assert c.confidence > 0.0
        assert 0.0 < c.confidence <= 1.0

    def test_short_sequence_better(self):
        engine = ConfidenceEngine()
        c1 = WorkflowCandidate(
            name="short",
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True),
            ],
            repetition_count=5,
        )
        c2 = WorkflowCandidate(
            name="long",
            steps=[
                WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True),
            ] + [WorkflowStep(tool_name="shell_exec", args={"cmd": "echo"}, ok=True)] * 15,
            repetition_count=5,
        )
        score1 = engine.compute(c1)
        score2 = engine.compute(c2)
        assert score1 > score2  # Shorter = higher confidence

    def test_repetition_curve(self):
        """Test that repetition score increases with count."""
        engine = ConfidenceEngine()

        scores = []
        for count in range(1, 21):
            c = WorkflowCandidate(
                name="test",
                steps=[WorkflowStep(tool_name="shell_exec", args={"cmd": "ls"}, ok=True)],
                repetition_count=count,
            )
            scores.append(engine._repetition_score(c))

        # Should be monotonically non-decreasing (sigmoid)
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1] - 0.001
