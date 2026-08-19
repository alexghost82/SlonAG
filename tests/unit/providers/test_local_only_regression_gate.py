"""W14-T20: Local-Only Regression Gate tests.

Proves that under local_only routing, offline network mode, or fully_local privacy profile,
Slon NEVER falls back to cloud providers (Gemini, OpenAI, OpenRouter) under any failure condition.
"""

import pytest

from providers.contracts import ModelInfo
from providers.errors import CapabilityError
from providers.routing import CLOUD_PROVIDER_IDS, select_model


def _make_cloud_models() -> list[ModelInfo]:
    return [
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            text=True,
            tool_calling=True,
            vision=True,
            streaming=True,
            local=False,
        ),
        ModelInfo(
            provider_id="openai",
            model_id="gpt-4o",
            display_name="GPT-4o",
            text=True,
            tool_calling=True,
            vision=True,
            streaming=True,
            local=False,
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="anthropic/claude-3-5-sonnet",
            display_name="Claude 3.5 Sonnet",
            text=True,
            tool_calling=True,
            vision=True,
            streaming=True,
            local=False,
        ),
    ]


def _make_local_model(*, tool_calling: bool = True) -> ModelInfo:
    return ModelInfo(
        provider_id="ollama",
        model_id="llama3.2:3b",
        display_name="Llama 3.2 3B",
        text=True,
        tool_calling=tool_calling,
        vision=False,
        streaming=True,
        local=True,
    )


class TestLocalOnlyRegressionGate:
    """Gate 1: No Cloud Escape Under Hard Local Constraints."""

    def test_local_only_mode_with_no_available_local_models(self) -> None:
        """Scenario 1 & 2: Ollama and llama.cpp unavailable in local_only mode."""
        cloud_models = _make_cloud_models()
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=cloud_models,
                routing_mode="local_only",
                configured_provider_id="ollama",
                required_role="chat",
                availability={m.provider_id: False for m in cloud_models},
            )
        assert "no model satisfies" in str(exc_info.value)
        assert exc_info.value.provider_id not in CLOUD_PROVIDER_IDS

    def test_local_only_mode_with_missing_configured_local_model(self) -> None:
        """Scenario 3: Configured local model is missing from candidates."""
        cloud_models = _make_cloud_models()
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=cloud_models,
                routing_mode="local_only",
                configured_provider_id="ollama",
                configured_model_id="nonexistent-model",
            )
        assert "no model satisfies" in str(exc_info.value)

    def test_local_only_mode_with_tool_calling_disabled(self) -> None:
        """Scenario 4: Local model exists but tool_calling is False."""
        candidates = _make_cloud_models() + [_make_local_model(tool_calling=False)]
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=candidates,
                routing_mode="local_only",
                configured_provider_id="ollama",
                required_capabilities=("tool_calling",),
            )
        assert "tool_calling" in str(exc_info.value)

    def test_local_only_mode_when_local_health_check_fails(self) -> None:
        """Scenario 5: Local provider health check fails (availability=False)."""
        local_model = _make_local_model()
        candidates = _make_cloud_models() + [local_model]
        availability = {"ollama": False, "gemini": True, "openai": True}
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=candidates,
                routing_mode="local_only",
                configured_provider_id="ollama",
                availability=availability,
            )
        assert "no model satisfies" in str(exc_info.value)

    def test_local_only_mode_lacks_required_capability(self) -> None:
        """Scenario 6: Local model lacks required capability (e.g. vision)."""
        local_model = _make_local_model()  # vision=False
        candidates = _make_cloud_models() + [local_model]
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=candidates,
                routing_mode="local_only",
                configured_provider_id="ollama",
                required_capabilities=("vision",),
            )
        assert "vision" in str(exc_info.value)

    def test_offline_network_mode_prevents_cloud_fallback(self) -> None:
        """Scenario 7: network_mode='offline' prevents selection of cloud models."""
        cloud_models = _make_cloud_models()
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=cloud_models,
                routing_mode="local_first",  # Even with local_first, offline hard-blocks cloud
                configured_provider_id="openai",
                network_mode="offline",
            )
        assert "no model satisfies" in str(exc_info.value)

    def test_fully_local_privacy_profile_prevents_cloud_fallback(self) -> None:
        """Scenario 7: privacy_profile='fully_local' hard-blocks cloud models."""
        cloud_models = _make_cloud_models()
        with pytest.raises(CapabilityError) as exc_info:
            select_model(
                candidates=cloud_models,
                routing_mode="cloud_first",  # Even with cloud_first, fully_local hard-blocks cloud
                configured_provider_id="gemini",
                privacy_profile="fully_local",
            )
        assert "no model satisfies" in str(exc_info.value)
