"""ProactiveStore — persistence layer for ProactiveAgent state.

Handles save/load of the agent's state and configuration to disk,
supporting graceful restart and crash recovery.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

from mark.proactive.types import (
    ProactiveAgentConfig,
    ProactiveOptInStatus,
    ProactiveState,
)

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class ProactiveStore:
    """File-backed persistent storage for ProactiveAgent state.

    Stores:
    - Schema version
    - ProactiveState (opt_in, counters, etc.)
    - ProactiveAgentConfig (threshold, cooldown, etc.)
    """

    def __init__(self, path: str = "memory/proactive.json") -> None:
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def save(self, state: ProactiveState, config: ProactiveAgentConfig) -> None:
        """Persist state and config to disk."""
        data = {
            "_schema_version": _SCHEMA_VERSION,
            "_saved_at": time.time(),
            "state": {
                "opt_in": state.opt_in.value,
                "enabled": state.enabled,
                "total_processed": state.total_processed,
                "total_executed": state.total_executed,
                "total_ignored": state.total_ignored,
                "last_event_provenance": state.last_event_provenance,
                "last_updated_at": state.last_updated_at,
            },
            "config": {
                "enabled": config.enabled,
                "opt_in": config.opt_in.value,
                "relevance_threshold": config.relevance_threshold,
                "cooldown_seconds": config.cooldown_seconds,
                "dedup_window_seconds": config.dedup_window_seconds,
                "max_actions_per_minute": config.max_actions_per_minute,
                "log_level": config.log_level,
                "persistence_path": config.persistence_path,
            },
        }
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            logger.info("ProactiveStore saved: %s", self._path)
        except OSError as exc:
            logger.error("ProactiveStore save failed: %s", exc)

    def load(self) -> tuple[ProactiveState, ProactiveAgentConfig]:
        """Load state and config from disk. Returns defaults if missing."""
        default_state = ProactiveState()
        default_config = ProactiveAgentConfig()

        path = Path(self._path)
        if not path.exists():
            logger.info("ProactiveStore: no file at %s, using defaults", self._path)
            return default_state, default_config

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            version = data.get("_schema_version", 0)
            if version != _SCHEMA_VERSION:
                logger.warning(
                    "ProactiveStore: schema version %d (expected %d), migrating",
                    version,
                    _SCHEMA_VERSION,
                )

            state_data = data.get("state", {})
            state = ProactiveState(
                opt_in=ProactiveOptInStatus(state_data.get("opt_in", "off")),
                enabled=state_data.get("enabled", True),
                total_processed=state_data.get("total_processed", 0),
                total_executed=state_data.get("total_executed", 0),
                total_ignored=state_data.get("total_ignored", 0),
                last_event_provenance=state_data.get("last_event_provenance"),
                last_updated_at=state_data.get("last_updated_at", time.time()),
            )

            config_data = data.get("config", {})
            config = ProactiveAgentConfig(
                enabled=config_data.get("enabled", True),
                opt_in=ProactiveOptInStatus(config_data.get("opt_in", "read_only")),
                relevance_threshold=config_data.get(
                    "relevance_threshold", 0.5
                ),
                cooldown_seconds=config_data.get("cooldown_seconds", 60.0),
                dedup_window_seconds=config_data.get(
                    "dedup_window_seconds", 300.0
                ),
                max_actions_per_minute=config_data.get(
                    "max_actions_per_minute", 10
                ),
                log_level=config_data.get("log_level", "INFO"),
                persistence_path=config_data.get(
                    "persistence_path", "memory/proactive.json"
                ),
            )
            return state, config

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("ProactiveStore load failed: %s, using defaults", exc)
            return default_state, default_config

    def exists(self) -> bool:
        return Path(self._path).exists()
