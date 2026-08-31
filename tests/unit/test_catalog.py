"""Tests for config/catalog.py — provider model catalog query layer."""

from __future__ import annotations

from config.catalog import (
    clear_cache,
    get_all_static_models,
    get_model_info,
    get_static_models,
    model_capabilities_display,
    model_exists_in_catalog,
    resolve_capabilities,
)
from providers.contracts import ModelInfo


class TestGetStaticModels:
    """Test static catalog queries."""

    def test_gemini_returns_static_models(self):
        models = get_static_models("gemini")
        assert len(models) >= 4
        model_ids = {m.model_id for m in models}
        assert "gemini-2.5-flash" in model_ids
        assert "gemini-2.5-pro" in model_ids
        assert "gemini-2.5-flash-lite" in model_ids
        assert "gemini-embedding-001" in model_ids

    def test_gemini_model_capabilities(self):
        models = get_static_models("gemini")
        flash = next(m for m in models if m.model_id == "gemini-2.5-flash")
        assert flash.text is True
        assert flash.tool_calling is True
        assert flash.vision is True
        assert flash.streaming is True
        assert flash.structured_output is True
        assert flash.local is False

    def test_gemini_embedding_model(self):
        models = get_static_models("gemini")
        emb = next(m for m in models if m.model_id == "gemini-embedding-001")
        assert emb.text is False
        assert emb.embeddings is True

    def test_non_gemini_returns_empty(self):
        assert get_static_models("openai") == ()
        assert get_static_models("openrouter") == ()
        assert get_static_models("ollama") == ()
        assert get_static_models("llama_cpp") == ()
        assert get_static_models("local") == ()

    def test_unknown_provider_returns_empty(self):
        assert get_static_models("nonexistent") == ()


class TestGetModelInfo:
    """Test model info lookup."""

    def test_gemini_flash(self):
        info = get_model_info("gemini", "gemini-2.5-flash")
        assert info is not None
        assert info.model_id == "gemini-2.5-flash"
        assert info.text is True
        assert info.tool_calling is True
        assert info.vision is True

    def test_gemini_embedding(self):
        info = get_model_info("gemini", "gemini-embedding-001")
        assert info is not None
        assert info.embeddings is True
        assert info.text is False

    def test_openai_gpt4o(self):
        info = get_model_info("openai", "gpt-4o")
        assert info is not None
        assert info.text is True
        assert info.vision is True
        assert info.tool_calling is True

    def test_openai_whisper(self):
        info = get_model_info("openai", "whisper-1")
        assert info is not None
        assert info.audio_input is True

    def test_ollama_llama32(self):
        info = get_model_info("ollama", "llama3.2")
        assert info is not None
        assert info.text is True
        assert info.tool_calling is True

    def test_unknown_provider_returns_none(self):
        assert get_model_info("nonexistent", "foo") is None

    def test_unknown_model_returns_none(self):
        assert get_model_info("gemini", "nonexistent-model") is None

    def test_openrouter_model_in_overrides(self):
        info = get_model_info("openrouter", "google/gemini-2.5-flash")
        assert info is not None
        assert info.tool_calling is True
        assert info.vision is True


class TestResolveCapabilities:
    """Test capability resolution."""

    def test_known_model_returns_capabilities(self):
        caps = resolve_capabilities("gemini", "gemini-2.5-flash")
        assert caps["text"] is True
        assert caps["tool_calling"] is True
        assert caps["vision"] is True
        assert caps["streaming"] is True

    def test_unknown_model_returns_empty(self):
        caps = resolve_capabilities("unknown", "foo")
        assert caps == {}

    def test_unknown_provider_returns_empty(self):
        caps = resolve_capabilities("unknown", "any-model")
        assert caps == {}


class TestModelCapabilitiesDisplay:
    """Test capability display strings."""

    def test_gemini_flash_display_ru(self):
        from i18n import set_locale
        set_locale("ru")

        info = get_model_info("gemini", "gemini-2.5-flash")
        display = model_capabilities_display(info)
        assert "Текст" in display
        assert "Инструменты" in display
        assert "Зрение" in display
        assert "Структурированный" in display

    def test_gemini_flash_display_en(self):
        from i18n import set_locale
        set_locale("en")

        info = get_model_info("gemini", "gemini-2.5-flash")
        display = model_capabilities_display(info)
        assert "Text" in display
        assert "Tools" in display
        assert "Vision" in display

    def test_embedding_model_display(self):
        from i18n import set_locale
        set_locale("en")

        info = get_model_info("gemini", "gemini-embedding-001")
        display = model_capabilities_display(info)
        assert "Embeddings" in display

    def test_text_only_model_display(self):
        from i18n import set_locale
        set_locale("en")

        info = get_model_info("openai", "gpt-4o")
        display = model_capabilities_display(info)
        assert "Text" in display
        assert "Tools" in display


class TestModelExistsInCatalog:
    """Test model existence check."""

    def test_known_gemini_model_exists(self):
        assert model_exists_in_catalog("gemini", "gemini-2.5-flash") is True

    def test_unknown_model_not_exists(self):
        assert model_exists_in_catalog("gemini", "nonexistent") is False

    def test_unknown_provider_not_exists(self):
        assert model_exists_in_catalog("nonexistent", "any") is False


class TestGetAllStaticModels:
    """Test all static models retrieval."""

    def test_returns_gemini_models(self):
        models = get_all_static_models()
        assert len(models) >= 4
        all_ids = {m.model_id for m in models}
        assert "gemini-2.5-flash" in all_ids


class TestCacheClear:
    """Test catalog cache clearing."""

    def test_clear_cache(self):
        # First call populates cache
        get_static_models("gemini")

        # Clear cache
        clear_cache()

        # Next call should re-fetch
        models = get_static_models("gemini")
        assert len(models) >= 4
