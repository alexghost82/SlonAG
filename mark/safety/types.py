"""Risk levels, sources, and the decision returned by ``authorize``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum


class RiskLevel(IntEnum):
    """In-code risk. The model cannot choose this value."""

    READ = 0
    NOTIFY = 1
    CONFIRM = 2
    EXACT_CONFIRM = 3
    BIOMETRIC = 4


class UntrustedSource(StrEnum):
    """Provenance of a tool call. Only ``user`` may start risk ≥ 2."""

    USER = "user"
    WEB = "web"
    DOCUMENT = "document"
    IMAGE = "image"
    TOOL_RESULT = "tool_result"


class DecisionKind(StrEnum):
    """What the caller must do before running the tool."""

    ALLOW = "allow"
    NOTIFY = "notify"
    CONFIRM = "confirm"
    EXACT_CONFIRM = "exact_confirm"
    BIOMETRIC = "biometric"
    DENY = "deny"


TRUSTED_SOURCES = frozenset({UntrustedSource.USER})

KIND_FOR_RISK: dict[RiskLevel, DecisionKind] = {
    RiskLevel.READ: DecisionKind.ALLOW,
    RiskLevel.NOTIFY: DecisionKind.NOTIFY,
    RiskLevel.CONFIRM: DecisionKind.CONFIRM,
    RiskLevel.EXACT_CONFIRM: DecisionKind.EXACT_CONFIRM,
    RiskLevel.BIOMETRIC: DecisionKind.BIOMETRIC,
}


@dataclass(frozen=True)
class SafetyDecision:
    """Authorization outcome. ``args`` is a copy for a later UI prompt."""

    kind: DecisionKind
    tool_name: str
    risk: RiskLevel
    source: UntrustedSource
    intent: str
    args: Mapping[str, object]
    reason: str = ""


def is_trusted_source(source: UntrustedSource) -> bool:
    """Return True only for a direct user request."""
    return source in TRUSTED_SOURCES


def parse_source(value: UntrustedSource | str) -> UntrustedSource:
    """Coerce a string to ``UntrustedSource``."""
    if isinstance(value, UntrustedSource):
        return value
    return UntrustedSource(value)


__all__ = [
    "KIND_FOR_RISK",
    "TRUSTED_SOURCES",
    "DecisionKind",
    "RiskLevel",
    "SafetyDecision",
    "UntrustedSource",
    "is_trusted_source",
    "parse_source",
]
