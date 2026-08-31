"""Persistence layer for proactive agent state.

Provides save/load for events, decisions, cooldown state, and
relevance cache so the proactive layer survives restarts.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mark.proactive.types import CooldownEntry, ProactiveDecision


class ProactivePersistence:
    """JSON-file persistence for proactive agent state.

    Saves:
    - Last seen events (for dedup restart)
    - Decisions
    - Cooldown state
    - Configuration
    """

    def __init__(self, store_path: str | Path | None = None) -> None:
        if store_path is None:
            import tempfile
            tmpdir = Path(tempfile.mkdtemp(prefix="proactive_"))
            self._store_path = tmpdir / "proactive_state.json"
        else:
            self._store_path = Path(store_path)
            self._store_path.parent.mkdir(parents=True, exist_ok=True)

        self._state: dict[str, Any] = {
            "decisions": [],
            "cooldowns": {},
            "fingerprint_cache": {},
            "last_seen_at": time.time(),
            "version": 1,
        }

    def save(self) -> None:
        """Write current state to disk."""
        try:
            self._store_path.write_text(
                json.dumps(self._state, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass  # Best-effort persistence

    def load(self) -> None:
        """Read state from disk. Best-effort."""
        if not self._store_path.exists():
            return
        try:
            raw = self._store_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._state.update(data)
        except (json.JSONDecodeError, OSError):
            pass

    def save_decision(self, decision: ProactiveDecision) -> None:
        """Persist a decision."""
        entry = {
            "event_id": decision.event_id,
            "action": decision.action.value,
            "reason": decision.reason,
            "risk": decision.risk.value,
            "approval_required": decision.approval_required,
            "details": decision.details,
            "timestamp": time.time(),
        }
        self._state["decisions"].append(entry)
        # Keep only the last 100 decisions
        if len(self._state["decisions"]) > 100:
            self._state["decisions"] = self._state["decisions"][-100:]
        self.save()

    def load_decisions(self) -> list[dict[str, Any]]:
        """Load persisted decisions."""
        self.load()
        return list(self._state.get("decisions", []))

    def save_cooldown(self, entry: CooldownEntry) -> None:
        """Persist a cooldown entry."""
        self._state["cooldowns"][entry.source_type] = {
            "next_allowed": entry.next_allowed,
            "cooldown_seconds": entry.cooldown_seconds,
            "count": entry.count,
        }
        self.save()

    def load_cooldown(self, source_type: str) -> CooldownEntry | None:
        """Restore a cooldown entry from disk."""
        self.load()
        raw = self._state.get("cooldowns", {}).get(source_type)
        if raw is None:
            return None
        return CooldownEntry(
            source_type=source_type,
            cooldown_seconds=float(raw.get("cooldown_seconds", 30.0)),
            next_allowed=float(raw.get("next_allowed", 0.0)),
            count=int(raw.get("count", 0)),
        )

    @property
    def path(self) -> Path:
        return self._store_path
