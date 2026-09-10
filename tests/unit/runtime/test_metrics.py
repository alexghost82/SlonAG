from __future__ import annotations

import pytest

from runtime.metrics import METRIC_NAMES, inc, reset_for_tests, snapshot


def test_metrics_catalog_and_increment() -> None:
    reset_for_tests()
    assert "agent_requests_total" in METRIC_NAMES
    assert "gateway_auth_failures" in METRIC_NAMES
    inc("agent_requests_total")
    inc("tool_timeouts_total", 2)
    values = snapshot()
    assert values["agent_requests_total"] == 1
    assert values["tool_timeouts_total"] == 2
    assert "sk-" not in str(values)
    try:
        inc("not_a_real_metric")
        raise AssertionError("unknown metrics must be rejected")
    except ValueError:
        pass


@pytest.mark.asyncio
async def test_agent_loop_run_increments_catalog_counters() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from agent.runtime import AgentLoop
    from providers.contracts import ChatResponse, ModelInfo

    reset_for_tests()
    model = ModelInfo(
        provider_id="test",
        model_id="test-model",
        display_name="Test model",
        text=True,
        tool_calling=True,
    )
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=ChatResponse(text="ok", provider_id="test", model_id="test-model"))
    loop = AgentLoop(provider=provider, model=model)
    result = await loop.run("hello")
    assert result.ok is True
    values = snapshot()
    assert values["agent_requests_total"] >= 1
    assert values["agent_loop_turns"] >= 1
    assert values["provider_requests_total"] >= 1
    assert "sk-" not in str(values)
