"""Persistent storage for self-improvement state."""

from __future__ import annotations

import json
from pathlib import Path

from .types import SelfImprovementRecord, SelfImprovementState


def _path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "memory" / "self_improvement.json"


def load_state(path: str | None = None) -> SelfImprovementState:
    target = Path(path) if path else _path()
    if not target.exists():
        return SelfImprovementState()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SelfImprovementState()

    state = SelfImprovementState()
    state.observations_count = raw.get("observations_count", 0)
    state.candidates_generated = raw.get("candidates_generated", 0)
    state.approved_count = raw.get("approved_count", 0)
    state.rolled_back_count = raw.get("rolled_back_count", 0)
    state.improvements = {
        k: SelfImprovementRecord._record_from_dict(v)
        for k, v in raw.get("improvements", {}).items()
    }
    return state


def save_state(state: SelfImprovementState, path: str | None = None) -> None:
    target = Path(path) if path else _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "observations_count": state.observations_count,
        "candidates_generated": state.candidates_generated,
        "approved_count": state.approved_count,
        "rolled_back_count": state.rolled_back_count,
        "improvements": {
            k: v._to_dict() for k, v in state.improvements.items()
        },
    }
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
