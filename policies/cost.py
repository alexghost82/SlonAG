"""Local aggregated cost ledger.

Records input/output token usage and an estimate when ``ModelInfo.cost`` is
known. Totals are stored as daily and monthly aggregates in a caller-injected
file. This module does not call providers, does not log secrets, and refuses
``memory/*.json`` paths.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers.contracts import ModelInfo

_LEDGER_VERSION = 1


@dataclass(frozen=True)
class UsageTotals:
    """Aggregated token counts and estimated cost for one period."""

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: ModelInfo | None = None,
) -> float:
    """Return ``(input + output) * model.cost`` when cost is known, else 0."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if model is None or model.cost is None:
        return 0.0
    return (input_tokens + output_tokens) * float(model.cost)


class CostLedger:
    """Persist daily and monthly usage aggregates at an injected path."""

    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._reject_memory_path(self.path)
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def daily(self) -> UsageTotals:
        return self._totals("daily")

    @property
    def monthly(self) -> UsageTotals:
        return self._totals("monthly")

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: ModelInfo | None = None,
        *,
        estimated_cost: float | None = None,
    ) -> float:
        """Add token usage and persist updated daily/monthly aggregates."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        cost = (
            float(estimated_cost)
            if estimated_cost is not None
            else estimate_cost(input_tokens, output_tokens, model)
        )
        if cost < 0:
            raise ValueError("estimated_cost must be non-negative")
        payload = self._load()
        day_key, month_key = self._period_keys()
        self._accumulate(
            payload["daily"],
            day_key,
            input_tokens,
            output_tokens,
            cost,
        )
        self._accumulate(
            payload["monthly"],
            month_key,
            input_tokens,
            output_tokens,
            cost,
        )
        self._write(payload)
        return cost

    def would_exceed(
        self,
        limit: float,
        additional: float = 0.0,
        *,
        period: str = "daily",
    ) -> bool:
        """Return True if current period total plus ``additional`` exceeds ``limit``."""
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if additional < 0:
            raise ValueError("additional must be non-negative")
        if period not in {"daily", "monthly"}:
            raise ValueError("period must be 'daily' or 'monthly'")
        current = self.daily.estimated_cost if period == "daily" else self.monthly.estimated_cost
        return (current + additional) > limit

    def _period_keys(self) -> tuple[str, str]:
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        return now.date().isoformat(), now.strftime("%Y-%m")

    def _totals(self, period: str) -> UsageTotals:
        payload = self._load()
        day_key, month_key = self._period_keys()
        key = day_key if period == "daily" else month_key
        row = payload[period].get(key, {})
        return UsageTotals(
            input_tokens=int(row.get("input_tokens", 0)),
            output_tokens=int(row.get("output_tokens", 0)),
            estimated_cost=float(row.get("estimated_cost", 0.0)),
        )

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": _LEDGER_VERSION, "daily": {}, "monthly": {}}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("cost ledger file must contain an object")
        daily = raw.get("daily", {})
        monthly = raw.get("monthly", {})
        if not isinstance(daily, dict) or not isinstance(monthly, dict):
            raise ValueError("cost ledger aggregates must be objects")
        return {
            "version": _LEDGER_VERSION,
            "daily": daily,
            "monthly": monthly,
        }

    def _write(self, payload: dict[str, Any]) -> None:
        self._reject_memory_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _accumulate(
        bucket: dict[str, Any],
        key: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        current = bucket.get(key, {})
        if not isinstance(current, dict):
            current = {}
        bucket[key] = {
            "input_tokens": int(current.get("input_tokens", 0)) + input_tokens,
            "output_tokens": int(current.get("output_tokens", 0)) + output_tokens,
            "estimated_cost": float(current.get("estimated_cost", 0.0)) + cost,
        }

    @staticmethod
    def _reject_memory_path(path: Path) -> None:
        if "memory" in path.parts and path.suffix == ".json":
            raise ValueError("cost ledger must not use memory/*.json")


__all__ = [
    "CostLedger",
    "UsageTotals",
    "estimate_cost",
]
