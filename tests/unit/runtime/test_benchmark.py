from __future__ import annotations

import pytest

from runtime.benchmark import SCENARIOS, measure_async, summarize


def test_benchmark_reports_nearest_rank_percentiles_and_environment() -> None:
    report = summarize(
        "tool_call",
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        definition="dispatch to normalized result",
        environment="test-host",
    )
    assert report.count == 10
    assert report.median_ms == 5.5
    assert report.p90_ms == 9
    assert report.p95_ms == 10
    assert report.environment == "test-host"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_every_wave18_scenario_can_be_measured_separately(scenario: str) -> None:
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1

    report = await measure_async(
        scenario,
        operation,
        samples=3,
        warmup=1,
        definition="fixture boundary",
    )
    assert report.scenario == scenario
    assert report.count == 3
    assert calls == 4


@pytest.mark.asyncio
async def test_single_sample_is_rejected_as_benchmark_statistics() -> None:
    with pytest.raises(ValueError, match="at least two"):
        await measure_async(
            "local_text", lambda: _noop(), samples=1, definition="invalid"
        )


async def _noop() -> None:
    return None
