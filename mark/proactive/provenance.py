"""Provenance tracker — logs the origin and lifecycle of every event.

Every trigger that enters the ProactiveAgent receives a provenance
record that tracks: source → filter → decision → action → result.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProvenanceRecord:
    """Complete provenance chain for one event."""

    event_id: str                    # from ProactiveTrigger.provenance_id
    source: str                      # TriggerSource value
    event_type: str
    filter_result: str | None = None     # "pass"/"fail"
    decision: str | None = None        # ProactiveDecision value
    action_type: str | None = None
    result_status: str | None = None   # "executed"/"pending"/"denied"
    created_at: float = field(
        default_factory=lambda: time.time()
    )
    updated_at: float = field(
        default_factory=lambda: time.time()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def update(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k) and v is not None:
                setattr(self, k, v)
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "event_type": self.event_type,
            "filter_result": self.filter_result,
            "decision": self.decision,
            "action_type": self.action_type,
            "result_status": self.result_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


class ProvenanceTracker:
    """In-memory provenance store with optional file persistence."""

    def __init__(self, persist_path: str | None = None) -> None:
        self._records: dict[str, ProvenanceRecord] = {}
        self._persist_path = persist_path
        if persist_path:
            Path(persist_path).parent.mkdir(parents=True, exist_ok=True)

    def record(self, trigger) -> ProvenanceRecord:
        """Create a new provenance record from a trigger and persist."""
        rec = ProvenanceRecord(
            event_id=trigger.provenance_id,
            source=trigger.source.value,
            event_type=trigger.event_type,
        )
        self._records[rec.event_id] = rec
        self._maybe_persist()
        return rec

    def update(self, event_id: str, **kwargs: Any) -> None:
        rec = self._records.get(event_id)
        if rec:
            rec.update(**kwargs)
            self._maybe_persist()

    def get(self, event_id: str) -> ProvenanceRecord | None:
        return self._records.get(event_id)

    def list_all(self, limit: int = 100) -> list[ProvenanceRecord]:
        sorted_recs = sorted(
            self._records.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return sorted_recs[:limit]

    def _maybe_persist(self) -> None:
        if not self._persist_path:
            return
        try:
            data = [r.to_dict() for r in self._records.values()]
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._persist_path)
        except OSError as exc:
            logger.warning("Failed to persist provenance: %s", exc)

    @classmethod
    def from_disk(cls, persist_path: str) -> ProvenanceTracker:
        tracker = cls(persist_path=persist_path)
        path = Path(persist_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    rec = ProvenanceRecord(
                        event_id=item["event_id"],
                        source=item["source"],
                        event_type=item["event_type"],
                        filter_result=item.get("filter_result"),
                        decision=item.get("decision"),
                        action_type=item.get("action_type"),
                        result_status=item.get("result_status"),
                        created_at=item.get("created_at", 0.0),
                        updated_at=item.get("updated_at", 0.0),
                        metadata=item.get("metadata", {}),
                    )
                    tracker._records[rec.event_id] = rec
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Could not load provenance from disk: %s", exc)
        return tracker
