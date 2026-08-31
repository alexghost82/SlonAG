"""Provider model catalog query layer.

Reads from provider catalog modules without modifying them.  All public
functions are synchronous so they can be called from the UI thread or
test code.  Network calls are NOT performed — only static catalog data
is exposed here.

Owned by Agent 02 (Provider / Model Settings UI).  Read-only access to
providers/* modules.
"""

from __future__ import annotations

from typing import Any

from providers.contracts import ModelInfo

# ─── Static Gemini catalog ──────────────────────────────────────────────────


def _load_gemini_models() -> tuple[ModelInfo, ...]:
    """Return the static Gemini model list from the provider catalog."""
    try:
        from providers.gemini.catalog import GEMINI_MODELS  # noqa: F401
        return GEMINI_MODELS
    except Exception:
        return ()


# ─── Known model overrides (local providers + OpenAI) ───────────────────────

_KNOWN_MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    # ollama family overrides — pulled from providers/local/capabilities.py
    "ollama:llama3.1": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
    },
    "ollama:llama3.2": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
    },
    "ollama:qwen2.5": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
    },
    # OpenAI model capability hints (conservative, from provider's
    # _model_info + conservative_capabilities logic)
    "openai:gpt-4o": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
        "vision": True,
    },
    "openai:gpt-4o-mini": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
        "vision": True,
    },
    "openai:whisper-1": {
        "text": True,
        "streaming": True,
        "audio_input": True,
    },
    "openai:tts-1": {
        "audio_output": True,
    },
    "openai:embeddings": {
        "embeddings": True,
    },
    # OpenRouter — capabilities come from their catalog endpoint;
    # we keep a small known list for offline UI rendering.
    "openrouter:google/gemini-2.5-flash": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
        "vision": True,
        "structured_output": True,
    },
    "openrouter:openai/gpt-4o": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
        "vision": True,
    },
    "openrouter:meta-llama/llama-3.3-70b": {
        "text": True,
        "streaming": True,
        "tool_calling": True,
    },
}


def _get_overrides(provider_id: str, model_id: str) -> dict[str, Any]:
    """Return capability overrides for a known model, or empty dict."""
    key = f"{provider_id}:{model_id}"
    return dict(_KNOWN_MODEL_OVERRIDES.get(key, {}))


# ─── Public API ─────────────────────────────────────────────────────────────

def get_static_models(provider_id: str) -> tuple[ModelInfo, ...]:
    """Return the static catalog models for *provider_id*.

    For cloud providers this reads from the provider catalog modules.
    For local providers the result is empty — local models are discovered
    at runtime via HTTP.
    """
    if provider_id == "gemini":
        return _load_gemini_models()
    # OpenRouter/OpenAI catalogs require network calls to query;
    # no static list here (by design — we don't hardcode).
    return ()


def get_model_info(provider_id: str, model_id: str) -> ModelInfo | None:
    """Return a ``ModelInfo`` for *model_id*, or ``None`` if unknown.

    Priority:
    1. Static catalog (Gemini).
    2. Known overrides table (local + OpenAI).
    3. ``None`` — caller should treat the model as having no guaranteed capabilities.
    """
    # 1. Check static catalog first
    for m in get_static_models(provider_id):
        if m.model_id == model_id:
            return m

    # 2. Check known overrides — build a minimal ModelInfo
    overrides = _get_overrides(provider_id, model_id)
    if overrides:
        # Ensure defaults for text/streaming if not specified
        if "text" not in overrides:
            overrides = dict(overrides, text=True)
        if "streaming" not in overrides:
            overrides["streaming"] = True
        return ModelInfo(
            provider_id=provider_id,
            model_id=model_id,
            display_name=model_id,
            **overrides,  # type: ignore[arg-type]
        )

    return None


def resolve_capabilities(provider_id: str, model_id: str) -> dict[str, Any]:
    """Return a capability dict for a model.

    Returns an empty dict when the model is not in the known list.
    """
    info = get_model_info(provider_id, model_id)
    if info is None:
        return {}
    fields = (
        "text",
        "streaming",
        "tool_calling",
        "structured_output",
        "vision",
        "audio_input",
        "audio_output",
        "embeddings",
    )
    return {
        field: getattr(info, field, False)
        for field in fields
    }


def model_capabilities_display(info: ModelInfo) -> str:
    """Return a short human-readable capability summary.

    Example: ``"Текст, Инструменты, Зрение"``
    """
    from i18n import t
    parts: list[str] = []
    if info.text:
        parts.append(t("catalog.cap_text"))
    if info.tool_calling:
        parts.append(t("catalog.cap_tools"))
    if info.vision:
        parts.append(t("catalog.cap_vision"))
    if info.audio_input:
        parts.append(t("catalog.cap_audio_in"))
    if info.audio_output:
        parts.append(t("catalog.cap_audio_out"))
    if info.embeddings:
        parts.append(t("catalog.cap_embeddings"))
    if info.structured_output:
        parts.append(t("catalog.cap_structured"))
    if info.streaming:
        parts.append(t("catalog.cap_streaming"))
    return ", ".join(parts) if parts else t("catalog.cap_unknown")


def provider_validation_message(provider_id: str) -> str | None:
    """Return a validation note for a provider, or None if the provider is fine."""
    known_providers = frozenset({
        "gemini", "openai", "openrouter", "local", "ollama", "llama_cpp", "openai_compat"
    })
    if provider_id not in known_providers:
        return t("catalog.err_unknown_provider", provider=provider_id)
    return None


# ─── Import-time catalog cache (for UI performance) ─────────────────────────

_gemini_cache: tuple[ModelInfo, ...] | None = None


def _ensure_gemini_cache() -> tuple[ModelInfo, ...]:
    global _gemini_cache
    if _gemini_cache is None:
        _gemini_cache = _load_gemini_models()
    return _gemini_cache


def get_all_static_models() -> list[ModelInfo]:
    """Return all static catalog models across providers."""
    return list(_ensure_gemini_cache())


def model_exists_in_catalog(provider_id: str, model_id: str) -> bool:
    """Return True if the model exists in any known catalog source."""
    info = get_model_info(provider_id, model_id)
    return info is not None


def clear_cache() -> None:
    """Clear cached catalog data. Intended for tests."""
    global _gemini_cache
    _gemini_cache = None
