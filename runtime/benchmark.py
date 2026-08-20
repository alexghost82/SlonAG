"""Reproducible, payload-free helpers for Wave 18 runtime benchmarks."""

from __future__ import annotations

import math
import platform
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


SCENARIOS = frozenset(
    {"local_text", "cloud_text", "voice_round_trip", "tool_call", "multi_tool_turn"}
)


@dataclass(frozen=True)
class BenchmarkReport:
    scenario: str
    count: int
    min_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    max_ms: float
    environment: str
    definition: str


def summarize(
    scenario: str,
    samples_ms: list[float],
    *,
    definition: str,
    environment: str | None = None,
) -> BenchmarkReport:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown benchmark scenario: {scenario}")
    if not samples_ms:
        raise ValueError("at least one sample is required")
    values = sorted(max(0.0, float(item)) for item in samples_ms)
    rank = lambda percentile: values[max(0, math.ceil(percentile * len(values)) - 1)]
    return BenchmarkReport(
        scenario=scenario,
        count=len(values),
        min_ms=round(values[0], 3),
        median_ms=round(statistics.median(values), 3),
        p90_ms=round(rank(0.90), 3),
        p95_ms=round(rank(0.95), 3),
        max_ms=round(values[-1], 3),
        environment=environment or f"Python {platform.python_version()} {sys.platform}",
        definition=definition,
    )


async def measure_async(
    scenario: str,
    operation: Callable[[], Awaitable[object]],
    *,
    samples: int,
    warmup: int = 1,
    definition: str,
) -> BenchmarkReport:
    if samples < 2:
        raise ValueError("benchmark statistics require at least two samples")
    for _ in range(max(0, warmup)):
        await operation()
    measured: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        await operation()
        measured.append((time.perf_counter() - started) * 1000.0)
    return summarize(scenario, measured, definition=definition)


__all__ = ["BenchmarkReport", "SCENARIOS", "measure_async", "summarize"]
