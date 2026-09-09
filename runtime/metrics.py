"""Process-local counters. Never include secrets or user content."""

from __future__ import annotations

import threading
from collections import defaultdict

_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = defaultdict(int)

METRIC_NAMES = (
    "agent_requests_total",
    "agent_failures_total",
    "agent_loop_turns",
    "provider_requests_total",
    "provider_failures_total",
    "provider_latency_ms_total",
    "tool_calls_total",
    "tool_failures_total",
    "tool_latency_ms_total",
    "tool_timeouts_total",
    "jobs_pending",
    "jobs_running",
    "jobs_failed",
    "memory_reads_total",
    "memory_writes_total",
    "memory_failures_total",
    "gateway_connections",
    "gateway_auth_failures",
)


def inc(name: str, value: int = 1) -> None:
    if name not in METRIC_NAMES:
        raise ValueError(f"unknown metric: {name}")
    with _LOCK:
        _COUNTERS[name] += int(value)


def snapshot() -> dict[str, int]:
    with _LOCK:
        return {name: int(_COUNTERS.get(name, 0)) for name in METRIC_NAMES}


def reset_for_tests() -> None:
    with _LOCK:
        _COUNTERS.clear()


__all__ = ["METRIC_NAMES", "inc", "reset_for_tests", "snapshot"]
