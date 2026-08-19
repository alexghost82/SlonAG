from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from policies.cost import CostLedger, estimate_cost
from providers.contracts import ModelInfo


def _model(*, cost: float | None) -> ModelInfo:
    return ModelInfo(
        provider_id="openai",
        model_id="unit-test",
        display_name="unit test",
        text=True,
        cost=cost,
    )


def test_estimate_cost_uses_model_info_when_known() -> None:
    model = _model(cost=0.01)
    assert estimate_cost(10, 5, model) == pytest.approx(0.15)
    assert estimate_cost(10, 5, _model(cost=None)) == 0.0
    assert estimate_cost(10, 5, None) == 0.0


def test_ledger_aggregates_daily_and_monthly(tmp_path: Path) -> None:
    path = tmp_path / "cost-ledger.json"
    now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    ledger = CostLedger(path, now=lambda: now)
    first = ledger.add_usage(10, 5, _model(cost=0.01))
    second = ledger.add_usage(2, 3, _model(cost=0.01))
    assert first == pytest.approx(0.15)
    assert second == pytest.approx(0.05)
    assert ledger.daily.input_tokens == 12
    assert ledger.daily.output_tokens == 8
    assert ledger.daily.estimated_cost == pytest.approx(0.20)
    assert ledger.monthly.input_tokens == 12
    assert ledger.monthly.output_tokens == 8
    assert ledger.monthly.estimated_cost == pytest.approx(0.20)


def test_ledger_persists_on_injected_path(tmp_path: Path) -> None:
    path = tmp_path / "ledgers" / "usage.json"
    now = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
    CostLedger(path, now=lambda: now).add_usage(4, 1, _model(cost=0.5))
    reloaded = CostLedger(path, now=lambda: now)
    assert reloaded.daily.input_tokens == 4
    assert reloaded.daily.output_tokens == 1
    assert reloaded.daily.estimated_cost == pytest.approx(2.5)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["daily"]["2026-08-15"]["input_tokens"] == 4
    assert payload["monthly"]["2026-08"]["output_tokens"] == 1
    assert "memory" not in path.parts
    stored = path.read_text(encoding="utf-8")
    assert "api_key" not in stored
    assert "sk-" not in stored


def test_would_exceed_uses_daily_total(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    ledger = CostLedger(path)
    ledger.add_usage(8, 2, _model(cost=0.01))
    assert ledger.would_exceed(0.20) is False
    assert ledger.would_exceed(0.10) is False
    assert ledger.would_exceed(0.09) is True
    assert ledger.would_exceed(0.12, additional=0.03) is True
    assert ledger.would_exceed(1.0, period="monthly") is False


def test_unknown_model_cost_still_aggregates_tokens(tmp_path: Path) -> None:
    path = tmp_path / "tokens-only.json"
    ledger = CostLedger(path)
    assert ledger.add_usage(7, 9, _model(cost=None)) == 0.0
    assert ledger.daily.input_tokens == 7
    assert ledger.daily.output_tokens == 9
    assert ledger.daily.estimated_cost == 0.0
    assert ledger.would_exceed(0.0) is False
    assert ledger.would_exceed(0.0, additional=0.01) is True


def test_rejects_memory_json_path(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory" / "long_term.json"
    with pytest.raises(ValueError, match="memory"):
        CostLedger(memory_path)


def test_rejects_negative_usage(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path / "neg.json")
    with pytest.raises(ValueError, match="non-negative"):
        ledger.add_usage(-1, 0)
    with pytest.raises(ValueError, match="non-negative"):
        estimate_cost(0, -2)
