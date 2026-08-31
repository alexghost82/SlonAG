"""Permission boundary for proactive actions.

Ensures the proactive agent cannot execute dangerous or user-affecting
actions without explicit user approval. Uses a whitelist/denylist
pattern.
"""
from __future__ import annotations

from typing import Any

from acta.proactive.errors import (
    CODE_ACTION_BLOCKED,
    CODE_PERM_DENIED,
    ActionBlockedError,
    PermissionDeniedError,
)
from acta.proactive.types import (
    ProactiveAction,
    ProactiveDecision,
    ProactiveEvent,
    RiskLevel,
    SAFE_AUTO_ACTIONS,
)


class PermissionBoundary:
    """Gatekeeper that prevents unsafe autonomous actions.

    Rules:
    - SAFE_AUTO_ACTIONS (notify, remember, check_status, log_event,
      update_health) can auto-execute.
    - Everything else requires user approval.
    - No dangerous actions (file delete, system config change, network
      change, etc.) are ever auto-executed.
    """

    def __init__(
        self,
        allow_list: frozenset[str] | None = None,
    ) -> None:
        self._allow_list = allow_list or SAFE_AUTO_ACTIONS

    def can_auto_execute(self, decision: ProactiveDecision) -> bool:
        """Return True if the decision can be auto-executed.

        Only SAFE_AUTO_ACTIONS are allowed; everything else needs
        user approval.
        """
        if decision.action == ProactiveAction.EXECUTE:
            details = decision.details
            action_name = details.get("action_name", "")
            return action_name in self._allow_list

        if decision.action == ProactiveAction.PROPOSE:
            return True  # proposing is safe

        if decision.action == ProactiveAction.REMEMBER:
            return True  # remembering is safe

        if decision.action == ProactiveAction.NOTIFY:
            return True

        return False

    def validate(self, event: ProactiveEvent, action: ProactiveAction) -> None:
        """Raise an error if the action is not allowed for this source."""
        if action == ProactiveAction.EXECUTE:
            details = event.payload
            action_name = details.get("action_name", details.get("intent", ""))
            if action_name not in self._allow_list:
                raise ActionBlockedError(
                    f"Action '{action_name}' is not in the auto-execute allowlist. "
                    "Requires user approval."
                )

    def evaluate(self, decision: ProactiveDecision) -> ProactiveDecision:
        """Apply permission boundary to a decision.

        Upgrades EXECUTE → REQUEST_APPROVAL if not safe.
        """
        if decision.action == ProactiveAction.EXECUTE:
            if not self.can_auto_execute(decision):
                decision = ProactiveDecision(
                    action=ProactiveAction.REQUEST_APPROVAL,
                    event_id=decision.event_id,
                    reason="Permission boundary: EXECUTE requires user approval",
                    risk=RiskLevel.HIGH,
                    details=decision.details,
                    approval_required=True,
                )
        return decision

    @property
    def allow_list(self) -> frozenset[str]:
        return self._allow_list


class ProactiveAuthorization:
    """Check if a user has approved a proactive decision."""

    def __init__(self) -> None:
        self._approved: dict[str, bool] = {}

    def approve(self, event_id: str) -> None:
        """Mark an event_id as approved by the user."""
        self._approved[event_id] = True

    def is_approved(self, event_id: str) -> bool:
        return self._approved.get(event_id, False)

    def reject(self, event_id: str) -> None:
        """Mark as rejected. Removes from approved set."""
        self._approved.pop(event_id, None)

    def clear(self, event_id: str) -> None:
        """Clear all state for an event."""
        self._approved.pop(event_id, None)
