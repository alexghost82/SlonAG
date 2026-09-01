"""Thread-safe control plane shared by desktop UI/runtime and remote API."""

from __future__ import annotations

import platform
import threading
import time
from collections.abc import Callable, Mapping
from copy import deepcopy

EventSink = Callable[[Mapping[str, object]], object]
CommandHandler = Callable[[], object]
TextHandler = Callable[[str], object]
ApprovalHandler = Callable[
    [str, Mapping[str, object], str, str, str | None], bool
]


class ControlPlaneUnavailable(RuntimeError):
    """Raised when the desktop runtime has not bound a requested operation."""


class DesktopControlPlane:
    """Single source of truth for remote-visible desktop state.

    It owns no sockets and no secrets. PyQt and ``SlonLive`` update it, while
    ``DesktopControlListener`` reads snapshots and dispatches approved commands.
    """

    def __init__(
        self,
        *,
        provider_id: str = "gemini",
        model_id: str | None = None,
        network_mode: str = "hybrid",
        privacy_profile: str = "personal_local",
    ) -> None:
        self._lock = threading.RLock()
        self._reply_condition = threading.Condition(self._lock)
        self._chat_lock = threading.Lock()
        self._reply_sequence = 0
        self._latest_reply = ""
        self._started_at = time.time()
        self._state: dict[str, object] = {
            "online": True,
            "paired": True,
            "provider_id": provider_id,
            "model_id": model_id,
            "network_mode": network_mode,
            "privacy_profile": privacy_profile,
            "assistant_state": "INITIALISING",
            "mic_active": True,
            "local_tts_available": False,
            "local_stt_available": False,
            "desktop_api_active": False,
            "active_tasks": 0,
            "pending_approvals": 0,
        }
        self._metrics: dict[str, object] = {
            "cpu_percent": None,
            "memory_percent": None,
            "network_m_bps": None,
            "gpu_percent": None,
            "temperature_celsius": None,
            "uptime_seconds": None,
            "process_count": None,
            "os_name": platform.system(),
        }
        self._handlers: dict[str, CommandHandler] = {}
        self._text_handler: TextHandler | None = None
        self._approval_handler: ApprovalHandler | None = None
        self._event_sinks: list[EventSink] = []
        self._log: list[dict[str, object]] = []

    def bind_text_handler(self, handler: TextHandler | None) -> None:
        with self._lock:
            self._text_handler = handler

    def bind_command(self, action: str, handler: CommandHandler | None) -> None:
        normalized = action.strip().lower()
        if not normalized:
            raise ValueError("action must not be empty")
        with self._lock:
            if handler is None:
                self._handlers.pop(normalized, None)
            else:
                self._handlers[normalized] = handler

    def bind_approval_handler(self, handler: ApprovalHandler | None) -> None:
        with self._lock:
            self._approval_handler = handler

    def add_event_sink(self, sink: EventSink) -> None:
        with self._lock:
            if sink not in self._event_sinks:
                self._event_sinks.append(sink)

    def remove_event_sink(self, sink: EventSink) -> None:
        with self._lock:
            self._event_sinks = [item for item in self._event_sinks if item != sink]

    def update_state(self, **values: object) -> None:
        with self._lock:
            self._state.update(values)
            snapshot = deepcopy(self._state)
        self.publish("status", snapshot)

    def update_metrics(self, **values: object) -> None:
        with self._lock:
            self._metrics.update(values)

    def append_log(self, text: str) -> None:
        message = str(text).strip()
        if not message:
            return
        entry: dict[str, object] = {
            "event": "log",
            "text": message[:4000],
            "timestamp": time.time(),
        }
        with self._lock:
            self._log.append(entry)
            del self._log[:-500]
            if message.lower().startswith("slon:") or message.lower().startswith("jarvis:"):
                self._latest_reply = message.split(":", 1)[1].strip()
                self._reply_sequence += 1
                self._reply_condition.notify_all()
        self._fan_out(entry)

    def recent_log(self, *, limit: int = 100) -> list[dict[str, object]]:
        bounded = max(1, min(int(limit), 500))
        with self._lock:
            return deepcopy(self._log[-bounded:])

    def status_snapshot(self) -> dict[str, object]:
        with self._lock:
            state = deepcopy(self._state)
            metrics = deepcopy(self._metrics)
        metrics["uptime_seconds"] = max(0.0, time.time() - self._started_at)
        state["system_metrics"] = metrics
        return state

    def perform(self, action: str) -> object:
        normalized = action.strip().lower()
        with self._lock:
            handler = self._handlers.get(normalized)
        if handler is None:
            raise ControlPlaneUnavailable(f"runtime action is unavailable: {normalized}")
        result = handler()
        self.publish("runtime_control", {"action": normalized, "accepted": True})
        return result

    def submit_text(self, text: str) -> object:
        message = text.strip()
        if not message:
            raise ValueError("message must not be empty")
        with self._lock:
            handler = self._text_handler
        if handler is None:
            raise ControlPlaneUnavailable("desktop live session is not connected")
        result = handler(message)
        self.append_log(f"YOU (REMOTE): {message}")
        return result

    def submit_text_and_wait(self, text: str, *, timeout: float = 90.0) -> str | None:
        with self._chat_lock:
            with self._lock:
                start_sequence = self._reply_sequence
            self.submit_text(text)
            deadline = time.monotonic() + max(0.0, timeout)
            with self._reply_condition:
                while self._reply_sequence <= start_sequence:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._reply_condition.wait(timeout=remaining)
                return self._latest_reply

    def request_approval(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        source: str,
        reason: str,
        tool_call_id: str | None = None,
    ) -> bool:
        with self._lock:
            handler = self._approval_handler
        if handler is None:
            return False
        return bool(
            handler(tool_name, dict(arguments), source, reason, tool_call_id)
        )

    def publish(self, event: str, payload: Mapping[str, object]) -> None:
        envelope = {
            "event": str(event),
            "timestamp": time.time(),
            **dict(payload),
        }
        self._fan_out(envelope)

    def _fan_out(self, event: Mapping[str, object]) -> None:
        with self._lock:
            sinks = list(self._event_sinks)
        for sink in sinks:
            try:
                sink(deepcopy(dict(event)))
            except Exception:
                continue


__all__ = ["ControlPlaneUnavailable", "DesktopControlPlane"]
