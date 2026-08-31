"""Network modes, decisions, and journal entry shapes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NetworkMode(StrEnum):
    """Egress modes aligned with ``config.schema.NETWORK_MODES``."""

    OFFLINE = "offline"
    TOOLS_ONLY = "tools_only"
    HYBRID = "hybrid"


CLOUD_PROVIDER_IDS = frozenset({"gemini", "openai", "openrouter"})
PRIVACY_FULLY_LOCAL = "fully_local"


@dataclass(frozen=True)
class NetworkDecision:
    """Outcome of ``NetworkPolicy.check_request``."""

    allowed: bool
    reason: str
    domain: str = ""
    tool: str | None = None
    purpose: str = ""


@dataclass(frozen=True)
class NetworkJournalEntry:
    """One journaled network decision for a future UI. Never holds secrets."""

    tool: str | None
    domain: str
    time: float
    reason: str
    allowed: bool


__all__ = [
    "CLOUD_PROVIDER_IDS",
    "PRIVACY_FULLY_LOCAL",
    "NetworkDecision",
    "NetworkJournalEntry",
    "NetworkMode",
]
