"""Notification system for proactive events.

Handles delivery of notifications to various channels (UI, log,
email, etc.) with throttling per-channel.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class NotificationChannel(StrEnum):
    """Delivery channels for proactive notifications."""

    UI = "ui"                # in-app UI notification
    LOG = "log"              # application log
    EMAIL = "email"          # email (optional)
    PUSH = "push"            # push notification (optional)
    CUSTOM = "custom"        # user-defined callback


@dataclass(frozen=True)
class NotificationEvent:
    """A notification to be delivered."""

    channel: NotificationChannel
    title: str               # human-readable (Russian)
    body: str
    severity: str = "info"
    action_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationRouter:
    """Routes notifications to registered channel handlers.

    Supports:
    - Per-channel throttling (max N per minute)
    - Custom handlers via callbacks
    - Built-in fallback to logging
    """

    def __init__(self, default_throttle_per_minute: int = 5) -> None:
        self._handlers: dict[NotificationChannel, Callable[[NotificationEvent], None]] = {}
        self._default_throttle = default_throttle_per_minute
        self._throttle_counts: dict[NotificationChannel, list[float]] = defaultdict(list)

    def register_handler(
        self, channel: NotificationChannel, handler: Callable[[NotificationEvent], None]
    ) -> None:
        """Register a callback for a specific channel."""
        self._handlers[channel] = handler

    def send(self, event: NotificationEvent) -> bool:
        """Send a notification. Returns True if delivered."""
        # Check throttle
        if self._is_throttled(event.channel):
            logger.debug("Notification throttled: channel=%s", event.channel.value)
            return False

        handler = self._handlers.get(event.channel)
        if handler:
            try:
                handler(event)
                self._record_delivery(event.channel)
                return True
            except Exception:
                logger.exception(
                    "Notification handler failed: channel=%s", event.channel.value
                )
                return False

        # Fallback: log
        logger.info(
            "[Proactive Notif] %s [%s] %s: %s",
            event.channel.value.upper(),
            event.severity,
            event.title,
            event.body,
        )
        self._record_delivery(event.channel)
        return True

    def _is_throttled(self, channel: NotificationChannel) -> bool:
        now = time.time()
        cutoff = now - 60.0
        timestamps = self._throttle_counts[channel]
        self._throttle_counts[channel] = [
            t for t in timestamps if t > cutoff
        ]
        return len(self._throttle_counts[channel]) >= self._default_throttle

    def _record_delivery(self, channel: NotificationChannel) -> None:
        self._throttle_counts[channel].append(time.time())

    def set_throttle(self, channel: NotificationChannel, per_minute: int) -> None:
        self._default_throttle = per_minute

    def get_channel_counts(self) -> dict[str, int]:
        now = time.time()
        cutoff = now - 60.0
        return {
            ch.value: len([t for t in ts if t > cutoff])
            for ch, ts in self._throttle_counts.items()
        }
