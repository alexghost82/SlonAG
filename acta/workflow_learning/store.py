"""JSON-based persistence for workflow learning artifacts.

Stores:
  - WorkflowCandidate (JSON)
  - WorkflowTemplate (JSON)
  - ExecutionRecord (JSON)
  - Version history (JSON)

All data lives in a single JSON file with top-level keys:
  {
    "candidates": {id: {...}},
    "templates": {id: {...}},
    "versions": {candidate_id: [{version: N, ...}, ...]},
    "executions": {id: {...}},
    "metadata": {"schema_version": "1.0", "created_at": ...}
  }
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from acta.workflow_learning.types import (
    ExecutionRecord,
    ExecutionResult,
    WorkflowCandidate,
    WorkflowState,
    WorkflowTemplate,
)


class WorkflowStore:
    """Thread-safe JSON store for workflow learning data."""

    SCHEMA_VERSION = "1.0"

    def __init__(self, store_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = Path(store_path) if store_path else None
        self._data: dict[str, Any] = {
            "candidates": {},
            "templates": {},
            "versions": {},
            "executions": {},
            "metadata": {"schema_version": self.SCHEMA_VERSION, "updated_at": time.time()},
        }
        if self._path and self._path.exists():
            self._load()
        else:
            self._flush()

    @property
    def path(self) -> Path | None:
        return self._path

    # ------------------------------------------------------------------
    # Candidate CRUD
    # ------------------------------------------------------------------

    def save_candidate(self, candidate: WorkflowCandidate) -> None:
        """Save or update a workflow candidate."""
        with self._lock:
            self._data["candidates"][candidate.id] = self._serialize_candidate(candidate)
            self._record_version(candidate.id, candidate.version)
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()

    def get_candidate(self, candidate_id: str) -> WorkflowCandidate | None:
        """Load a candidate by ID."""
        with self._lock:
            raw = self._data["candidates"].get(candidate_id)
            if raw is None:
                return None
            return self._deserialize_candidate(raw)

    def list_candidates(
        self,
        *,
        state: WorkflowState | None = None,
        active_only: bool = False,
    ) -> list[WorkflowCandidate]:
        """List candidates, optionally filtered by state."""
        with self._lock:
            results = []
            for raw in self._data["candidates"].values():
                c = self._deserialize_candidate(raw)
                if state is not None and c.state != state:
                    continue
                if active_only and c.state not in (
                    WorkflowState.APPROVED,
                    WorkflowState.PARAMETERIZED,
                    WorkflowState.ACTIVE,
                ):
                    continue
                results.append(c)
            return sorted(results, key=lambda c: c.updated_at, reverse=True)

    def delete_candidate(self, candidate_id: str) -> bool:
        """Remove a candidate and its versions."""
        with self._lock:
            if candidate_id not in self._data["candidates"]:
                return False
            del self._data["candidates"][candidate_id]
            self._data["versions"].pop(candidate_id, None)
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()
            return True

    # ------------------------------------------------------------------
    # Template CRUD
    # ------------------------------------------------------------------

    def save_template(self, template: WorkflowTemplate) -> None:
        """Save a workflow template."""
        with self._lock:
            self._data["templates"][template.id] = self._serialize_template(template)
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()

    def get_template(self, template_id: str) -> WorkflowTemplate | None:
        """Load a template by ID."""
        with self._lock:
            raw = self._data["templates"].get(template_id)
            if raw is None:
                return None
            return self._deserialize_template(raw)

    def list_templates(self, *, active_only: bool = False) -> list[WorkflowTemplate]:
        """List templates."""
        with self._lock:
            results = []
            for raw in self._data["templates"].values():
                t = self._deserialize_template(raw)
                if active_only and t.state != WorkflowState.ACTIVE:
                    continue
                results.append(t)
            return sorted(results, key=lambda t: t.updated_at, reverse=True)

    def delete_template(self, template_id: str) -> bool:
        """Remove a template."""
        with self._lock:
            if template_id not in self._data["templates"]:
                return False
            del self._data["templates"][template_id]
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()
            return True

    # ------------------------------------------------------------------
    # Execution records
    # ------------------------------------------------------------------

    def save_execution(self, record: ExecutionRecord) -> None:
        """Save an execution record."""
        with self._lock:
            self._data["executions"][record.id] = self._serialize_execution(record)
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()

    def list_executions(
        self,
        workflow_id: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionRecord]:
        """List execution records."""
        with self._lock:
            results = []
            for raw in self._data["executions"].values():
                e = self._deserialize_execution(raw)
                if workflow_id is not None and e.workflow_id != workflow_id:
                    continue
                results.append(e)
            results.sort(key=lambda e: e.created_at, reverse=True)
            return results[:limit]

    def get_execution(self, record_id: str) -> ExecutionRecord | None:
        """Load an execution record by ID."""
        with self._lock:
            raw = self._data["executions"].get(record_id)
            if raw is None:
                return None
            return self._deserialize_execution(raw)

    # ------------------------------------------------------------------
    # Version management
    # ------------------------------------------------------------------

    def record_version(
        self,
        candidate_id: str,
        version: int,
        state: WorkflowState,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Record a version snapshot for a candidate."""
        with self._lock:
            versions = self._data["versions"].setdefault(candidate_id, [])
            versions.append({
                "version": version,
                "state": state.value,
                "timestamp": time.time(),
                "snapshot": snapshot or {},
            })
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()

    def get_versions(self, candidate_id: str) -> list[dict[str, Any]]:
        """Get version history for a candidate."""
        with self._lock:
            return list(self._data["versions"].get(candidate_id, []))

    def delete_versions(self, candidate_id: str) -> bool:
        """Delete version history for a candidate."""
        with self._lock:
            if candidate_id not in self._data["versions"]:
                return False
            del self._data["versions"][candidate_id]
            self._data["metadata"]["updated_at"] = time.time()
            self._flush()
            return True

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return store statistics."""
        with self._lock:
            return {
                "candidates": len(self._data["candidates"]),
                "templates": len(self._data["templates"]),
                "executions": len(self._data["executions"]),
                "schema_version": self.SCHEMA_VERSION,
            }

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _serialize_candidate(self, c: WorkflowCandidate) -> dict[str, Any]:
        d = asdict(c)
        d["state"] = c.state.value
        return d

    def _deserialize_candidate(self, raw: dict[str, Any]) -> WorkflowCandidate:
        from acta.workflow_learning.types import WorkflowCandidate, WorkflowStep
        d = dict(raw)
        d["state"] = WorkflowState(d["state"])
        # Reconstruct nested dataclass objects from dicts
        if d.get("steps"):
            d["steps"] = [
                WorkflowStep(**s) if isinstance(s, dict) else s
                for s in d["steps"]
            ]
        if d.get("parameter_slots"):
            d["parameter_slots"] = [
                self._deserialize_slot(s) if isinstance(s, dict) else s
                for s in d["parameter_slots"]
            ]
        return WorkflowCandidate(**d)

    @staticmethod
    def _deserialize_slot(raw: dict[str, Any]) -> Any:
        """Deserialize a ParameterSlot from a dict."""
        from acta.workflow_learning.types import ParameterSlot
        d = dict(raw)
        # Handle JSON-encoded defaults
        if "default" in d and d["default"] is not None and d["default"] != "":
            try:
                d["default"] = json.loads(d["default"])
            except (json.JSONDecodeError, TypeError):
                pass
        return ParameterSlot(**d)

    def _serialize_template(self, t: WorkflowTemplate) -> dict[str, Any]:
        d = asdict(t)
        d["state"] = t.state.value
        return d

    def _deserialize_template(self, raw: dict[str, Any]) -> WorkflowTemplate:
        d = dict(raw)
        d["state"] = WorkflowState(d["state"])
        return WorkflowTemplate(**d)

    def _serialize_execution(self, e: ExecutionRecord) -> dict[str, Any]:
        d = asdict(e)
        if e.result is not None and isinstance(e.result, ExecutionResult):
            d["result"] = asdict(e.result)
        return d

    def _deserialize_execution(self, raw: dict[str, Any]) -> ExecutionRecord:
        d = dict(raw)
        if d.get("result") is not None:
            from acta.workflow_learning.types import ExecutionResult
            if isinstance(d["result"], dict):
                d["result"] = ExecutionResult(**d["result"])
        return ExecutionRecord(**d)

    # ------------------------------------------------------------------
    # Internal persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._data = data
        except (json.JSONDecodeError, OSError):
            pass

    def _flush(self) -> None:
        if self._path:
            try:
                self._path.write_text(
                    json.dumps(self._data, indent=2, default=str), encoding="utf-8"
                )
            except OSError:
                pass

    def _record_version(
        self, candidate_id: str, version: int, state: WorkflowState | None = None
    ) -> None:
        versions = self._data["versions"].setdefault(candidate_id, [])
        versions.append({
            "version": version,
            "state": state.value if state else "unknown",
            "timestamp": time.time(),
        })
