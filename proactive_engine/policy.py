"""Policy engine for proactive agent.

Checks opt-in status, quiet periods, risk thresholds, and
action-level permissions before allowing execution.
"""

from __future__ import annotations

from typing import Any

from proactive_engine.types import (
    ProactiveAction,
    ProactiveAgentConfig,
    ProactiveDecision,
    ProactiveOptInStatus,
    ProactiveState,
    ProactiveTrigger,
    RiskLevel,
)


class PolicyChecker:
    """Evaluates policy rules for a proactive trigger decision."""

    # Mapping from opt-in mode to permitted actions
    _ACTION_MAP: dict[ProactiveOptInStatus, frozenset[ProactiveAction]] = {
        ProactiveOptInStatus.OFF: frozenset(),
        ProactiveOptInStatus.NOTIFY_ONLY: frozenset({ProactiveAction.NOTIFY}),
        ProactiveOptInStatus.NOTIFY_AND_PROPOSE: frozenset({
            ProactiveAction.NOTIFY, ProactiveAction.PROPOSE,
        }),
        ProactiveOptInStatus.FULL_AUTO: frozenset({
            ProactiveAction.NOTIFY, ProactiveAction.PROPOSE, ProactiveAction.EXECUTE,
        }),
    }

    # Risk level ordering for comparison
    _RISK_ORDER: dict[RiskLevel, int] = {
        RiskLevel.SAFE: 0,
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
    }

    def check(self, trigger: ProactiveTrigger, config: ProactiveAgentConfig) -> ProactiveDecision:
        """Run all policy checks and return a decision."""
        if not config.enabled:
            return ProactiveDecision(
                trigger=trigger,
                action=ProactiveAction.NOTIFY,
                reason="proactive agent is disabled (opt-in off)",
                state=ProactiveState.POLICY_BLOCKED,
                risk=RiskLevel.SAFE,
            )

        if self._is_in_quiet_period(config):
            return ProactiveDecision(
                trigger=trigger,
                action=ProactiveAction.NOTIFY,
                reason="trigger falls within quiet period",
                state=ProactiveState.POLICY_BLOCKED,
                risk=RiskLevel.SAFE,
            )

        permitted = self._ACTION_MAP.get(config.action_mode, frozenset())
        if not permitted:
            return ProactiveDecision(
                trigger=trigger,
                action=ProactiveAction.NOTIFY,
                reason="opt-in mode restricts all actions",
                state=ProactiveState.POLICY_BLOCKED,
                risk=RiskLevel.SAFE,
            )

        risk = self._assess_risk(trigger, config)
        if self._risk_exceeds(risk, config.max_allowed_risk):
            return ProactiveDecision(
                trigger=trigger,
                action=ProactiveAction.NOTIFY,
                reason=f"risk {risk.value} exceeds max {config.max_allowed_risk.value}",
                state=ProactiveState.POLICY_BLOCKED,
                risk=risk,
            )

        # Determine the best action allowed by opt-in mode
        action = self._select_action(trigger, config)
        return ProactiveDecision(
            trigger=trigger,
            action=action,
            reason=f"policy approved: mode={config.action_mode.value}, risk={risk.value}",
            state=ProactiveState.RELEVANT,
            risk=risk,
        )

    def decide_action(
        self,
        trigger: ProactiveTrigger,
        config: ProactiveAgentConfig,
        risk: RiskLevel,
    ) -> ProactiveAction:
        """Given a known risk, pick the action to take."""
        permitted = self._ACTION_MAP.get(config.action_mode, frozenset())
        if ProactiveAction.EXECUTE in permitted and not self._risk_exceeds(risk, config.max_allowed_risk):
            return ProactiveAction.EXECUTE
        if ProactiveAction.PROPOSE in permitted:
            return ProactiveAction.PROPOSE
        return ProactiveAction.NOTIFY

    def _is_in_quiet_period(self, config: ProactiveAgentConfig) -> bool:
        for qp in config.quiet_periods:
            if qp.active:
                return True
        return False

    def _assess_risk(self, trigger: ProactiveTrigger, config: ProactiveAgentConfig) -> RiskLevel:
        """Assign a risk level based on trigger attributes."""
        priority = trigger.priority
        if priority >= 0.9:
            return RiskLevel.HIGH
        if priority >= 0.7:
            return RiskLevel.MEDIUM
        if priority >= 0.4:
            return RiskLevel.LOW
        return RiskLevel.SAFE

    def _risk_exceeds(self, risk: RiskLevel, max_risk: RiskLevel) -> bool:
        return self._RISK_ORDER.get(risk, 0) > self._RISK_ORDER.get(max_risk, 3)

    def _select_action(self, trigger: ProactiveTrigger, config: ProactiveAgentConfig) -> ProactiveAction:
        """Select the highest-allowed action for this trigger."""
        risk = self._assess_risk(trigger, config)
        return self.decide_action(trigger, config, risk)
