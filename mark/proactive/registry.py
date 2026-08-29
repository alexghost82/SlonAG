"""EventSourceRegistry — manages registered event sources.

Sources declare their capabilities, severity ranges, and preferred
delivery channels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from mark.proactive.types import RiskLevel, TriggerSource

logger = logging.getLogger(__name__)


@dataclass
class EventSourceConfig:
    """Configuration for an event source."""

    source: TriggerSource
    enabled: bool = True
    default_severity: RiskLevel = RiskLevel.MEDIUM
    allowed_actions: list[RiskLevel] = field(default_factory=list)  # empty = all
    preferred_channels: list[str] = field(default_factory=lambda: ["ui", "log"])
    max_events_per_minute: int = 20
    description: str = ""


class EventSourceRegistry:
    """Registry of event sources with capability checks.

    Prevents unauthorized sources from triggering events and enforces
    per-source rate limits.
    """

    def __init__(self) -> None:
        self._sources: dict[TriggerSource, EventSourceConfig] = {}
        self._rates: dict[TriggerSource, list[float]] = {}

    def register(self, config: EventSourceConfig) -> None:
        """Register an event source configuration."""
        self._sources[config.source] = config
        logger.info("EventSourceRegistry: registered %s (%s)", config.source.value, config.description)

    def get_config(self, source: TriggerSource) -> EventSourceConfig | None:
        return self._sources.get(source)

    def is_registered(self, source: TriggerSource) -> bool:
        return source in self._sources

    def is_source_enabled(self, source: TriggerSource) -> bool:
        config = self._sources.get(source)
        return config is not None and config.enabled

    def check_severity(self, source: TriggerSource, severity: RiskLevel) -> bool:
        config = self._sources.get(source)
        if config is None:
            return False
        if not config.allowed_actions:
            return True
        return severity in config.allowed_actions

    def is_rate_limited(self, source: TriggerSource, max_per_min: int | None = None) -> bool:
        config = self._sources.get(source)
        if config is None:
            return True  # unknown source → rate limited
        limit = max_per_min or config.max_events_per_minute
        now = __import__("time").time()
        cutoff = now - 60.0
        timestamps = self._rates.setdefault(source, [])
        self._rates[source] = [t for t in timestamps if t > cutoff]
        if len(self._rates[source]) >= limit:
            return True
        self._rates[source].append(now)
        return False

    @property
    def registered_sources(self) -> list[TriggerSource]:
        return list(self._sources.keys())

    def get_all_configs(self) -> dict[TriggerSource, EventSourceConfig]:
        return dict(self._sources)
