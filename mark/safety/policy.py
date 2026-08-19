"""Headless SafetyPolicy: in-code risk, untrusted isolation, no tool calls."""

from __future__ import annotations

from collections.abc import Mapping

from mark.safety.errors import ArgValidationError
from mark.safety.registry import (
    effective_risk,
    risk_for as registry_risk_for,
    tool_spec,
    validate_args as registry_validate_args,
)
from mark.safety.types import (
    KIND_FOR_RISK,
    DecisionKind,
    RiskLevel,
    SafetyDecision,
    UntrustedSource,
    is_trusted_source,
    parse_source,
)
from mark.safety.urls import check_url as check_url_host


class SafetyPolicy:
    """Authorize tool calls from a fixed registry. Never executes a tool."""

    def risk_for(self, tool_name: str) -> RiskLevel:
        """Return the conservative registry risk. Arguments are not consulted."""
        return registry_risk_for(tool_name)

    def validate_args(self, tool_name: str, args: object) -> dict[str, object]:
        """Validate ``args`` against the in-code schema for ``tool_name``."""
        return registry_validate_args(tool_name, args)

    def check_url(self, url: str) -> None:
        """Reject non-http(s), private, loopback, link-local, and metadata URLs."""
        check_url_host(url)

    def authorize(
        self,
        tool_name: str,
        args: object,
        *,
        source: UntrustedSource | str,
        intent: str = "",
    ) -> SafetyDecision:
        """Decide whether ``tool_name`` may run. Untrusted sources cannot override."""
        spec = tool_spec(tool_name)
        parsed_source = _coerce_source(source)
        copied = _copy_args(tool_name, args)
        risk = effective_risk(tool_name, copied)
        if spec.deny:
            return SafetyDecision(
                kind=DecisionKind.DENY,
                tool_name=tool_name,
                risk=risk,
                source=parsed_source,
                intent=intent,
                args=copied,
                reason="Tool is refused by policy.",
            )
        if not is_trusted_source(parsed_source) and risk >= RiskLevel.CONFIRM:
            return SafetyDecision(
                kind=DecisionKind.DENY,
                tool_name=tool_name,
                risk=risk,
                source=parsed_source,
                intent=intent,
                args=copied,
                reason="Untrusted source cannot start a confirmation-level action.",
            )
        return SafetyDecision(
            kind=KIND_FOR_RISK[risk],
            tool_name=tool_name,
            risk=risk,
            source=parsed_source,
            intent=intent,
            args=copied,
            reason="",
        )


_DEFAULT = SafetyPolicy()


def risk_for(tool_name: str) -> RiskLevel:
    """Return the conservative in-code risk for ``tool_name``."""
    return _DEFAULT.risk_for(tool_name)


def validate_args(tool_name: str, args: object) -> dict[str, object]:
    """Validate ``args`` against the in-code schema for ``tool_name``."""
    return _DEFAULT.validate_args(tool_name, args)


def check_url(url: str) -> None:
    """Allow only public http(s) URLs. Does not use the network."""
    _DEFAULT.check_url(url)


def authorize(
    tool_name: str,
    args: object,
    *,
    source: UntrustedSource | str,
    intent: str = "",
) -> SafetyDecision:
    """Authorize a tool call. Untrusted sources cannot override policy."""
    return _DEFAULT.authorize(tool_name, args, source=source, intent=intent)


def _coerce_source(source: UntrustedSource | str) -> UntrustedSource:
    try:
        return parse_source(source)
    except ValueError:
        raise ArgValidationError("", "Source is not recognized.", field="source") from None


def _copy_args(tool_name: str, args: object) -> dict[str, object]:
    if not isinstance(args, Mapping):
        raise ArgValidationError(tool_name, "Tool arguments must be a mapping.")
    return {str(key): value for key, value in args.items()}


__all__ = [
    "SafetyPolicy",
    "authorize",
    "check_url",
    "risk_for",
    "validate_args",
]
