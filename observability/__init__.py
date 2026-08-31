"""Observability — unified runtime status and capability reporting.

This package exposes a single source of truth for the system's
operational state.  Every consumer queries here so that
*capability* and *status* reporting always reflects what is
actually working at runtime rather than what was statically
expected at build time.

Exports
-------
- RuntimeStatus — the canonical status dataclass
- get_runtime_status — resolve status from real probes
- get_capability_report — delegate to computer_control
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from observability.status import get_runtime_status
from observability.capabilities import get_capability_report, is_capable


@dataclass(frozen=True)
class RuntimeStatus:
    """Canonical snapshot of the system's runtime state."""

    online: bool = False
    paired: bool = False
    provider_id: str | None = None
    model_id: str | None = None
    network_mode: str = "offline"
    privacy_profile: str = "fully_local"
    active_tasks: int = 0
    pending_approvals: int = 0
    capabilities_ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "online": self.online,
            "paired": self.paired,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "network_mode": self.network_mode,
            "privacy_profile": self.privacy_profile,
            "active_tasks": self.active_tasks,
            "pending_approvals": self.pending_approvals,
            "capabilities_ok": self.capabilities_ok,
        }


def get_status() -> RuntimeStatus:
    """Return a live status snapshot reflecting actual runtime state.

    Unlike the old fake provider, this function probes the real
    backend before reporting.  If any probe fails the field is
    defaulted to a safe (false) value.
    """
    status = get_runtime_status()
    cap_report = get_capability_report()
    cap_ok = bool(
        cap_report.get("capabilities", {}).get("input", False)
        or cap_report.get("capabilities", {}).get("screenshot", False)
    )
    return RuntimeStatus(
        online=status.online,
        paired=status.paired,
        provider_id=status.provider_id,
        model_id=status.model_id,
        network_mode=status.network_mode,
        privacy_profile=status.privacy_profile,
        active_tasks=status.active_tasks,
        pending_approvals=status.pending_approvals,
        capabilities_ok=cap_ok,
    )


__all__ = [
    "RuntimeStatus",
    "get_status",
    "get_runtime_status",
    "get_capability_report",
    "is_capable",
]
