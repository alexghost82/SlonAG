from __future__ import annotations

import pytest

from providers.contracts import ModelInfo
from providers.errors import CapabilityError
from providers.routing import score_model, select_model


def _model(
    provider_id: str,
    model_id: str,
    *,
    cost: float | None,
    tool_calling: bool = True,
) -> ModelInfo:
    return ModelInfo(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        text=True,
        tool_calling=tool_calling,
        local=provider_id in {"local", "ollama", "llama_cpp"},
        cost=cost,
    )


def test_incapable_cheap_model_is_rejected_instead_of_scored() -> None:
    cheap = _model("ollama", "cheap", cost=0.0, tool_calling=False)
    expensive = _model("ollama", "capable", cost=5.0)

    with pytest.raises(CapabilityError, match="tool_calling"):
        score_model(
            cheap,
            required_capabilities=frozenset({"tool_calling"}),
            prefer_local=True,
            privacy_profile="standard",
            availability=True,
        )
    assert select_model(
        (cheap, expensive),
        routing_mode="local_only",
        configured_provider_id="ollama",
        required_capabilities={"tool_calling"},
    ) is expensive


def test_privacy_invalid_cloud_model_is_rejected() -> None:
    cloud = _model("openai", "cloud", cost=0.0)
    with pytest.raises(CapabilityError, match="privacy profile"):
        score_model(
            cloud,
            required_capabilities=frozenset(),
            prefer_local=False,
            privacy_profile="fully_local",
            availability=True,
        )


def test_suitable_local_scores_above_cloud_when_local_is_preferred() -> None:
    local = _model("ollama", "local", cost=2.0)
    cloud = _model("openai", "cloud", cost=0.0)
    kwargs = {
        "required_capabilities": frozenset({"tool_calling"}),
        "prefer_local": True,
        "privacy_profile": "standard",
        "availability": True,
    }
    assert score_model(local, **kwargs) > score_model(cloud, **kwargs)


def test_lower_cost_wins_within_valid_routing_tier() -> None:
    expensive = _model("openai", "expensive", cost=4.0)
    cheap = _model("gemini", "cheap", cost=0.5)
    assert select_model(
        (expensive, cheap),
        routing_mode="cloud_first",
        configured_provider_id="openai",
    ) is cheap


def test_equal_scores_use_configured_provider_then_stable_input_order() -> None:
    first = _model("gemini", "first", cost=1.0)
    configured = _model("openai", "configured", cost=1.0)
    later = _model("openai", "later", cost=1.0)
    candidates = (first, configured, later)

    selections = [
        select_model(
            candidates,
            routing_mode="cloud_first",
            configured_provider_id="openai",
        )
        for _ in range(5)
    ]
    assert selections == [configured] * 5
