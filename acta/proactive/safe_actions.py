"""Safe auto-executable action handlers.

These actions are considered safe enough that the proactive agent
can execute them without user approval (when the permission
boundary allows it).
"""
from __future__ import annotations

import logging
import time

from acta.proactive.types import ProactiveDecision

logger = logging.getLogger(__name__)


class SafeActionExecutor:
    """Executes only the allowed safe actions."""

    def execute(self, decision: ProactiveDecision) -> bool:
        """Execute the safe action. Returns True on success."""
        details = decision.details
        action_name = details.get("action_name", decision.action.value)

        if action_name == "notify":
            return self._handle_notify(decision)
        elif action_name == "remember":
            return self._handle_remember(decision)
        elif action_name == "check_status":
            return self._handle_check_status(decision)
        elif action_name == "log_event":
            return self._handle_log_event(decision)
        elif action_name == "update_health":
            return self._handle_update_health(decision)
        else:
            logger.warning("Unknown safe action: %s", action_name)
            return False

    def _handle_notify(self, decision: ProactiveDecision) -> bool:
        """Produce a notification for the user.

        In production this would push to UI/notifications.
        Here we just log it for testing purposes.
        """
        title = decision.details.get("title", "Proactive Notification")
        message = decision.details.get("message", decision.reason)
        logger.info("[proactive notify] %s: %s", title, message)
        return True

    def _handle_remember(self, decision: ProactiveDecision) -> bool:
        """Record the event for future reference.

        The decision details include data to store.
        """
        stored_data = decision.details.get("data", {})
        logger.info(
            "[proactive remember] event=%s stored=%d fields=%s",
            decision.event_id,
            time.time(),
            list(stored_data.keys()),
        )
        return True

    def _handle_check_status(self, decision: ProactiveDecision) -> bool:
        """Execute a status check.

        No side effects, just reads state.
        """
        check_type = decision.details.get("check_type", "system")
        logger.info("[proactive check_status] type=%s", check_type)
        return True

    def _handle_log_event(self, decision: ProactiveDecision) -> bool:
        """Log the event for audit trail."""
        logger.info(
            "[proactive log_event] event_id=%s source=%s",
            decision.event_id,
            decision.details.get("source_type", "unknown"),
        )
        return True

    def _handle_update_health(self, decision: ProactiveDecision) -> bool:
        """Update system health status."""
        health = decision.details.get("health", "ok")
        logger.info("[proactive update_health] health=%s", health)
        return True
