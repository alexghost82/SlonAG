"""Tests for provider/model settings persistence and validation.

Tests the integration between config/catalog.py, config/onboard.py,
and config/settings.py for provider and model selection.
"""

from __future__ import annotations

from config.catalog import (
    clear_cache,
    get_model_info,
    get_static_models,
    resolve_capabilities,
)
from config.onboard import (
    CLOUD_MODELS,
    LOCAL_MODELS,
    MODEL_CAPABILITIES,
    get_model_capabilities_summary,
    get_model_display,
    validate_model_for_provider,
    validate_model_id,
)
from config.schema import Settings, validate_settings
from config.settings import save_settings, load_settings
from config.settings import SETTINGS_PATH
import pytest


class TestCatalogIntegration:
    """Test that catalog data feeds into onboard config correctly."""

    def test_gemini_models_in_catalog(self):
        """Gemini models from static catalog are in MODEL_CAPABILITIES."""
        models = get_static_models("gemini")
        for m in models:
            if m.model_id in ("gemini-2.5-flash", "gemini-2.5-pro"):
                assert m.model_id in MODEL_CAPABILITIES, \
                    f"{m.model_id} should be in MODEL_CAPABILITIES"

    def test_model_capabilities_are_read_from_catalog(self):
        """MODEL_CAPABILITIES reflects the catalog data."""
        caps = MODEL_CAPABILITIES.get("gemini-2.5-flash", {})
        assert caps.get("text") is True
        assert caps.get("tool_calling") is True
        assert caps.get("vision") is True
        assert caps.get("streaming") is True
        assert caps.get("structured_output") is True

    def test_openai_model_capabilities(self):
        """OpenAI models from known overrides are in MODEL_CAPABILITIES."""
        caps = MODEL_CAPABILITIES.get("gpt-4o", {})
        assert caps.get("text") is True
        assert caps.get("vision") is True
        assert caps.get("tool_calling") is True

    def test_ollama_model_capabilities(self):
        """Ollama models from known overrides are in MODEL_CAPABILITIES."""
        caps = MODEL_CAPABILITIES.get("llama3.2", {})
        assert caps.get("text") is True
        assert caps.get("tool_calling") is True


class TestValidateModelForProvider:
    """Test model validation against provider."""

    def test_valid_gemini_model(self):
        ok, err = validate_model_for_provider("gemini", "gemini-2.5-flash")
        assert ok is True
        assert err is None

    def test_invalid_model_for_provider(self):
        # GPT-4o is NOT a Gemini model
        ok, err = validate_model_for_provider("gemini", "gpt-4o")
        assert ok is False

    def test_empty_model_is_valid(self):
        ok, err = validate_model_for_provider("gemini", "")
        assert ok is True

    def test_ollama_model_valid(self):
        ok, err = validate_model_for_provider("ollama", "llama3.2")
        assert ok is True

    def test_unknown_provider_invalid_model(self):
        ok, err = validate_model_for_provider("nonexistent", "foo")
        assert ok is False


class TestModelDisplay:
    """Test model display string generation."""

    def test_gemini_display_name(self):
        display = get_model_display("gemini", "gemini-2.5-flash")
        assert "2.5 Flash" in display or "Flash" in display

    def test_unknown_model_returns_id(self):
        display = get_model_display("unknown", "foo")
        assert display == "foo"

    def test_ollama_display(self):
        display = get_model_display("ollama", "llama3.2")
        # The display name comes from catalog override
        assert display in ("llama3.2", "Llama 3.2 8B")


class TestModelCapabilitiesSummary:
    """Test capability summary generation."""

    def test_gemini_summary_ru(self):
        from i18n import set_locale
        set_locale("ru")

        summary = get_model_capabilities_summary("gemini", "gemini-2.5-flash")
        assert "Текст" in summary
        assert "Инструменты" in summary

    def test_gemini_summary_en(self):
        from i18n import set_locale
        set_locale("en")

        summary = get_model_capabilities_summary("gemini", "gemini-2.5-flash")
        assert "Text" in summary
        assert "Tools" in summary

    def test_unknown_model_summary(self):
        from i18n import set_locale
        set_locale("ru")

        summary = get_model_capabilities_summary("unknown", "foo")
        # Should return a "not found" message
        assert summary != "foo"


class TestSettingsPersistence:
    """Test that provider/model settings persist correctly."""

    def test_save_and_load_provider(self, isolated_paths):
        """Provider ID survives save/load cycle."""
        settings = validate_settings({"provider_id": "openai"})
        save_settings(settings)

        loaded = load_settings()
        assert loaded.provider_id == "openai"

    def test_save_and_load_model(self, isolated_paths):
        """Model ID survives save/load cycle."""
        settings = validate_settings({"provider_id": "gemini", "model_id": "gemini-2.5-flash"})
        save_settings(settings)

        loaded = load_settings()
        assert loaded.provider_id == "gemini"
        assert loaded.model_id == "gemini-2.5-flash"

    def test_save_and_load_empty_model(self, isolated_paths):
        """Empty model_id (auto) survives save/load cycle."""
        settings = validate_settings({"provider_id": "openai", "model_id": ""})
        save_settings(settings)

        loaded = load_settings()
        assert loaded.model_id == ""

    def test_provider_validation_on_save(self, isolated_paths):
        """Invalid provider_id is rejected on save."""
        with pytest.raises(Exception):  # SettingsValidationError
            validate_settings({"provider_id": "nonexistent-provider"})

    def test_model_roles_persist(self, isolated_paths):
        """Model roles survive save/load cycle."""
        settings = validate_settings({
            "provider_id": "gemini",
            "model_roles": {"chat": "gemini-2.5-flash", "planning": "gemini-2.5-pro"},
        })
        save_settings(settings)

        loaded = load_settings()
        assert loaded.model_roles.chat == "gemini-2.5-flash"
        assert loaded.model_roles.planning == "gemini-2.5-pro"


class TestValidateModelId:
    """Test legacy validate_model_id function."""

    def test_empty_model_valid(self):
        ok, err = validate_model_id("gemini", "")
        assert ok is True

    def test_non_empty_model_valid(self):
        ok, err = validate_model_id("gemini", "gemini-2.5-flash")
        assert ok is True


class TestCLOUD_MODELS_BACKWARD_COMPAT:
    """Ensure CLOUD_MODELS and LOCAL_MODELS still work for legacy code."""

    def test_cLOUD_models_has_gemini(self):
        assert "gemini" in CLOUD_MODELS
        assert len(CLOUD_MODELS["gemini"]) >= 2

    def test_local_models_has_ollama(self):
        assert "ollama" in LOCAL_MODELS
        assert len(LOCAL_MODELS["ollama"]) >= 2
