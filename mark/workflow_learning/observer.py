"""Action sequence observer.

Hooks into the tool execution pipeline to record every tool call.
When a sequence repeats enough times, it becomes a workflow candidate.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from mark.workflow_learning.types import (
    ActionSequence,
    ActionSequenceEvent,
    ParameterSlot,
    WorkflowCandidate,
    WorkflowState,
    WorkflowStep,
)


@dataclass
class _BufferEntry:
    """One entry in the observation buffer."""

    event: ActionSequenceEvent
    result_ok: bool
    result_message: str
    result_data: dict[str, Any] | None = None
    started_at: float | None = None
    finished_at: float | None = None


class ActionObserver:
    """Observes tool executions and detects repeated sequences.

    The observer maintains a ring buffer of recent events. When a buffer
    completes (``mark_complete`` is called), the sequence is analyzed.
    If the sequence hash appears in history more than ``min_repetitions``,
    a ``WorkflowCandidate`` is created.
    """

    def __init__(
        self,
        store: Any = None,  # WorkflowStore or None
        min_repetitions: int = 3,
        buffer_size: int = 20,
    ) -> None:
        self._store = store
        self._min_repetitions = min_repetitions
        self._buffer_size = buffer_size
        self._buffer: list[_BufferEntry] = []
        self._lock = threading.Lock()
        self._history_path: Path | None = None
        self._history: dict[str, int] = {}  # sequence_hash -> count
        self._callbacks: list[Callable[[WorkflowCandidate], None]] = []
        self._load_history()

    @property
    def min_repetitions(self) -> int:
        return self._min_repetitions

    @min_repetitions.setter
    def min_repetitions(self, value: int) -> None:
        self._min_repetitions = value

    def set_store(self, store: Any) -> None:
        """Attach the workflow store (for persistence)."""
        self._store = store

    def set_history_path(self, path: str | Path) -> None:
        """Persist observed sequence counts to a file."""
        self._history_path = Path(path)
        self._load_history()

    def on_candidate_created(self, callback: Callable[[WorkflowCandidate], None]) -> None:
        """Register a callback for when a candidate is created."""
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Observation API
    # ------------------------------------------------------------------

    def record_event(self, event: ActionSequenceEvent, *, ok: bool, message: str = "",
                     data: dict[str, Any] | None = None,
                     started_at: float | None = None,
                     finished_at: float | None = None) -> None:
        """Add one tool execution to the observation buffer."""
        with self._lock:
            self._buffer.append(_BufferEntry(
                event=event,
                result_ok=ok,
                result_message=message,
                result_data=data,
                started_at=started_at,
                finished_at=finished_at,
            ))
            # Auto-complete when buffer is full
            if len(self._buffer) >= self._buffer_size:
                self.mark_complete()

    def record_step(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        ok: bool,
        message: str = "",
        data: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
        started_at: float | None = None,
        finished_at: float | None = None,
    ) -> None:
        """Record a single step (convenience wrapper)."""
        self.record_event(
            ActionSequenceEvent(tool_name=tool_name, args=args, tool_call_id=tool_call_id),
            ok=ok,
            message=message,
            data=data,
            started_at=started_at,
            finished_at=finished_at,
        )

    def mark_complete(self) -> ActionSequence | None:
        """Mark the current buffer as complete and analyze.

        Returns the action sequence if it qualifies as a candidate,
        or ``None`` if no new candidate was created.
        """
        with self._lock:
            if not self._buffer:
                return None
            steps_data = list(self._buffer)
            self._buffer.clear()

        seq = self._build_sequence(steps_data)

        # Analyze for repetition
        candidate = self._analyze_and_maybe_create(seq)
        return candidate

    def clear_buffer(self) -> None:
        """Discard the current buffer without analyzing."""
        with self._lock:
            self._buffer.clear()

    def get_buffer_size(self) -> int:
        return len(self._buffer)

    # ------------------------------------------------------------------
    # Sequence analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sequence(entries: list[_BufferEntry]) -> ActionSequence:
        steps = [
            WorkflowStep.from_tool_result(
                tool_name=e.event.tool_name,
                args=dict(e.event.args),
                ok=e.result_ok,
                message=e.result_message,
                data=e.result_data,
                started_at=e.started_at,
                finished_at=e.finished_at,
            )
            for e in entries
        ]
        return ActionSequence(
            steps=steps,
            success=all(s.ok for s in steps),
            created_at=time.time(),
        )

    @staticmethod
    def _sequence_hash(sequence: ActionSequence) -> str:
        """Hash the tool-name pattern (ignoring argument values).

        The hash key is the sequence of tool names and their success status,
        so we can detect repeated execution patterns regardless of the
        specific arguments used.
        """
        pattern_parts = []
        for step in sequence.steps:
            pattern_parts.append(f"{step.tool_name}:{'ok' if step.ok else 'fail'}")
        pattern = "|".join(pattern_parts)
        return hashlib.sha256(pattern.encode()).hexdigest()[:16]

    def _analyze_and_maybe_create(self, sequence: ActionSequence) -> ActionSequence | None:
        """Update repetition count and create candidate if threshold met."""
        seq_hash = self._sequence_hash(sequence)

        with self._lock:
            count = self._history.get(seq_hash, 0) + 1
            self._history[seq_hash] = count
            self._save_history()

        if count >= self._min_repetitions and sequence.success:
            candidate = self._create_candidate(sequence, seq_hash, count)
            self._notify_callbacks(candidate)
            return sequence

        return sequence

    def _create_candidate(
        self, sequence: ActionSequence, seq_hash: str, count: int
    ) -> WorkflowCandidate:
        """Create a WorkflowCandidate from a repeated sequence."""
        # Build a name from the tool chain
        tool_names = [s.tool_name for s in sequence.steps]
        name = "_then_".join(tool_names)

        candidate = WorkflowCandidate(
            name=name,
            description=f"Learned from {count} repeated successful executions of {len(tool_names)} steps: {' -> '.join(tool_names)}",
            steps=[s for s in sequence.steps],
            repetition_count=count,
            successful_executions=count,
            total_executions=count,
            provenance=sequence.session_id or "auto",
            state=WorkflowState.CANDIDATE,
        )

        # Persist if store is available
        if self._store is not None:
            self._store.save_candidate(candidate)

        return candidate

    def _notify_callbacks(self, candidate: WorkflowCandidate) -> None:
        for cb in self._callbacks:
            try:
                cb(candidate)
            except Exception:
                pass  # Don't break observation on callback errors

    # ------------------------------------------------------------------
    # History persistence
    # ------------------------------------------------------------------

    def _load_history(self) -> None:
        if self._history_path and self._history_path.exists():
            try:
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._history = {k: int(v) for k, v in data.items()}
            except (json.JSONDecodeError, OSError):
                self._history.clear()

    def _save_history(self) -> None:
        if self._history_path:
            try:
                self._history_path.write_text(
                    json.dumps(self._history, indent=2), encoding="utf-8"
                )
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def get_history(self) -> dict[str, int]:
        """Return the full repetition history."""
        with self._lock:
            return dict(self._history)

    def get_sequence_count(self, sequence_hash: str) -> int:
        """Return how many times a sequence has been observed."""
        with self._lock:
            return self._history.get(sequence_hash, 0)


# E2E compatibility: WorkflowObserver alias with simple record method
class WorkflowObserver:
    """Simplified WorkflowObserver for E2E tests.
    
    Wraps ActionObserver with a simple record API.
    """
    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._actions: list[dict[str, Any]] = []
        self._observer = ActionObserver(store=store)

    def record(self, name: str, success: bool = True, duration: float = 0.0,
               message: str = "", result_data: dict[str, Any] | None = None) -> None:
        """Record a simple workflow action for E2E tests."""
        from mark.workflow_learning.types import ActionSequenceEvent
        self._actions.append({
            "name": name,
            "success": success,
            "duration": duration,
            "message": message,
            "result_data": result_data,
        })
        # Also notify the underlying observer if it exists
        try:
            event = ActionSequenceEvent(
                tool_name=name,
                tool_args={"recorded": True},
                result_ok=success,
                result_message=message,
            )
            self._observer.record_event(event, ok=success, message=message, result_data=result_data)
        except Exception:
            pass

    def list_actions(self) -> list[dict[str, Any]]:
        """Return recorded actions."""
        return list(self._actions)

    def list_candidates(self) -> list[Any]:
        """Delegate to underlying observer/store."""
        if self._observer._store is not None:
            return self._observer._store.list_candidates()
        return []

    def set_store(self, store: Any) -> None:
        self._store = store
        self._observer.set_store(store)
