from __future__ import annotations

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
