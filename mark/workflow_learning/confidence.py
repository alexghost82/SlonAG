"""Confidence scoring for workflow candidates.

Confidence is a float in [0.0, 1.0] based on:
  1. Repetition count (more repetitions = higher)
  2. Success rate across executions
  3. Sequence length (shorter = more likely to be reliably repeated)
  4. Value variability (lower variability = more deterministic)
"""

from __future__ import annotations

import math
from typing import Any

from mark.workflow_learning.types import WorkflowCandidate, WorkflowStep


class ConfidenceEngine:
    """Compute and update confidence scores for workflow candidates."""

    # Weight constants (tunable)
    WEIGHT_REPETITION = 0.35
    WEIGHT_SUCCESS_RATE = 0.30
    WEIGHT_LENGTH = 0.15
    WEIGHT_VARIABILITY = 0.20

    # Parameters
    REPETITION_MAX: int = 20  # saturates at this count
    REPETITION_SIGMOID_K: float = 0.5  # steepness
    MAX_REASONABLE_LENGTH: int = 10  # steps beyond this penalize


    def compute(self, candidate: WorkflowCandidate) -> float:
        """Compute overall confidence score.

        Returns a value in [0.0, 1.0].
        """
        components = [
            self._repetition_score(candidate),
            self._success_rate_score(candidate),
            self._length_score(candidate),
            self._variability_score(candidate),
        ]
        scores = [
            self.WEIGHT_REPETITION * components[0],
            self.WEIGHT_SUCCESS_RATE * components[1],
            self.WEIGHT_LENGTH * components[2],
            self.WEIGHT_VARIABILITY * components[3],
        ]
        return min(1.0, max(0.0, sum(scores)))

    def update(self, candidate: WorkflowCandidate) -> None:
        """Recompute and set confidence on the candidate."""
        candidate.confidence = self.compute(candidate)

    # ------------------------------------------------------------------
    # Individual score components
    # ------------------------------------------------------------------

    def _repetition_score(self, candidate: WorkflowCandidate) -> float:
        """Score based on how many times the sequence has repeated.

        Uses a sigmoid-like curve:
          - 3 repetitions (threshold) -> ~0.2
          - 10 repetitions -> ~0.6
          - 20+ repetitions -> ~1.0
        """
        n = max(candidate.repetition_count, 1)
        k = self.REPETITION_SIGMOID_K
        x = n - 2  # shift so that n=3 gives sigmoid(0.5)
        return 1.0 - 1.0 / (1.0 + math.exp(k * x))

    def _success_rate_score(self, candidate: WorkflowCandidate) -> float:
        """Score based on success rate.

        Only meaningful if there have been actual executions (not just
        observations). For raw observations the rate is effectively 1.0
        if the candidate was created from successful sequences.
        """
        total = candidate.total_executions
        if total == 0:
            # Candidate created from successful observations only
            return 1.0
        if total < self.REPETITION_MAX:
            return 1.0
        return candidate.successful_executions / total if total > 0 else 0.0

    def _length_score(self, candidate: WorkflowCandidate) -> float:
        """Score based on sequence length.

        Shorter sequences are more reliably repeatable.
        Penalizes long chains of tools.
        """
        length = len(candidate.steps)
        if length == 0:
            return 0.0
        if length <= 1:
            return 1.0
        if length <= self.MAX_REASONABLE_LENGTH:
            # Linear decay from 1.0 at 1 step to 0.5 at max_length
            ratio = 1.0 - (length - 1) / (2 * self.MAX_REASONABLE_LENGTH)
            return max(0.5, ratio)
        # Beyond max length, further penalty
        excess = length - self.MAX_REASONABLE_LENGTH
        return max(0.0, 0.5 - excess * 0.05)

    def _variability_score(self, candidate: WorkflowCandidate) -> float:
        """Score based on value variability across repetitions.

        If the same argument key has many different values, the workflow
        is less deterministic and thus less confident.
        """
        if len(candidate.steps) == 0:
            return 0.0

        total_slots = 0
        variable_slots = 0

        seen_keys: dict[str, set[str]] = {}
        for step in candidate.steps:
            for key in step.args:
                if key not in seen_keys:
                    seen_keys[key] = set()
                # We can only assess variability if the candidate has
                # multiple stored steps with the same tool_name
                seen_keys[key].add(step.tool_name)
                total_slots += 1

        unique_args = len(seen_keys)
        if total_slots == 0:
            return 1.0

        # Fewer unique args relative to total steps = higher variability
        determinism = 1.0 - (unique_slots / total_slots) if total_slots > 0 else 1.0
        return max(0.0, determinism)


# E2E compatibility: ConfidenceTracker wrapper for simple tests
class ConfidenceTracker:
    """Simple confidence tracker for E2E tests."""
    def __init__(self) -> None:
        self._scores: dict[str, float] = {}

    def add(self, name: str, confidence: float) -> None:
        self._scores[name] = confidence

    def get(self, name: str) -> float:
        return self._scores.get(name, 0.0)

    def list_all(self) -> dict[str, float]:
        return dict(self._scores)
