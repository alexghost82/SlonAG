"""Provider model catalog and dynamic model discovery.

This module provides a canonical catalog of known models per provider and
facilitates dynamic model loading via provider ``list_models()`` calls.

Usage
-----
    # Static catalog lookup
    from config.models import MODEL_CATALOG, list_models_for_provider
    catalog = MODEL_CATALOG["openai"]

    # Dynamic discovery (requires an async provider instance)
    from config.models import discover_models
    models = await discover_models("openai", api_key=...)
"""

from __future__ import annotations

from typing import Any, Mapping

from providers.contracts import ModelInfo

# ── Canonical model catalog ──────────────────────────────────────────

MODEL_CATALOG: dict[str, list[ModelInfo]] = {
    # OpenAI models
    "openai": [
        ModelInfo(
            provider_id="openai",
            model_id="gpt-4o",
            display_name="GPT-4o",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=128_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="gpt-4o-mini",
            display_name="GPT-4o Mini",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=128_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="gpt-4-turbo",
            display_name="GPT-4 Turbo",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=128_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="gpt-4",
            display_name="GPT-4",
            text=True, streaming=True, tool_calling=True, vision=True,
            context_length=128_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="o3",
            display_name="o3",
            text=True, streaming=True,
            context_length=200_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="o3-mini",
            display_name="o3 Mini",
            text=True, streaming=True,
            context_length=200_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="o1",
            display_name="o1",
            text=True, streaming=True, vision=True,
            context_length=200_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="o1-mini",
            display_name="o1 Mini",
            text=True, streaming=True,
            context_length=128_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="o1-preview",
            display_name="o1 Preview",
            text=True, streaming=True,
            context_length=128_000,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="text-embedding-3-small",
            display_name="text-embedding-3-small",
            embeddings=True, text=True,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="whisper-1",
            display_name="Whisper 1",
            audio_input=True, text=True,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="tts-1",
            display_name="TTS 1",
            audio_output=True, text=True,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="tts-1-hd",
            display_name="TTS 1 HD",
            audio_output=True, text=True,
            source="OpenAI", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openai",
            model_id="dall-e-3",
            display_name="DALL·E 3",
            source="OpenAI", license="Proprietary",
        ),
    ],
    # Gemini models
    "gemini": [
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            text=True, streaming=True, tool_calling=True, vision=True,
            audio_input=True, audio_output=True,
            context_length=1_048_576,
            source="Google", license="Proprietary",
        ),
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.0-flash",
            display_name="Gemini 2.0 Flash",
            text=True, streaming=True, tool_calling=True, vision=True,
            context_length=1_048_576,
            source="Google", license="Proprietary",
        ),
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.0-flash-lite",
            display_name="Gemini 2.0 Flash Lite",
            text=True, streaming=True, tool_calling=True, vision=True,
            context_length=1_048_576,
            source="Google", license="Proprietary",
        ),
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.5-pro",
            display_name="Gemini 2.5 Pro",
            text=True, streaming=True, tool_calling=True, vision=True,
            audio_input=True, audio_output=True,
            context_length=1_048_576,
            source="Google", license="Proprietary",
        ),
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-exp-1206",
            display_name="Gemini Exp 1206",
            text=True, streaming=True, tool_calling=True, vision=True,
            audio_input=True, audio_output=True,
            context_length=2_097_152,
            source="Google", license="Proprietary",
        ),
        ModelInfo(
            provider_id="gemini",
            model_id="gemini-2.0-flash-thinking-exp",
            display_name="Gemini 2.0 Flash Thinking",
            text=True, streaming=True,
            context_length=1_310_720,
            source="Google", license="Proprietary",
        ),
        ModelInfo(
            provider_id="gemini",
            model_id="models/gemini-2.0-flash-001",
            display_name="Gemini 2.0 Flash (vertex)",
            text=True, streaming=True, tool_calling=True, vision=True,
            context_length=1_048_576,
            source="Google Vertex", license="Proprietary",
        ),
    ],
    # OpenRouter models
    "openrouter": [
        ModelInfo(
            provider_id="openrouter",
            model_id="anthropic/claude-3.5-sonnet",
            display_name="Claude 3.5 Sonnet",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=200_000,
            source="Anthropic via OpenRouter", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="anthropic/claude-3.5-sonnet:beta",
            display_name="Claude 3.5 Sonnet (beta)",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=200_000,
            source="Anthropic via OpenRouter", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="anthropic/claude-4-sonnet",
            display_name="Claude 4 Sonnet",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=200_000,
            source="Anthropic via OpenRouter", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="google/gemini-2.5-flash",
            display_name="Gemini 2.5 Flash (OR)",
            text=True, streaming=True, tool_calling=True, vision=True,
            audio_input=True,
            context_length=1_048_576,
            source="Google via OpenRouter", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="openai/gpt-4o",
            display_name="GPT-4o (OR)",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=128_000,
            source="OpenAI via OpenRouter", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="openai/gpt-4o-mini",
            display_name="GPT-4o Mini (OR)",
            text=True, streaming=True, tool_calling=True, vision=True,
            structured_output=True,
            context_length=128_000,
            source="OpenAI via OpenRouter", license="Proprietary",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="meta-llama/llama-3.1-70b",
            display_name="Llama 3.1 70B",
            text=True, streaming=True, tool_calling=True,
            context_length=128_000,
            source="Meta via OpenRouter", license="Apache 2.0",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="meta-llama/llama-3.1-8b",
            display_name="Llama 3.1 8B",
            text=True, streaming=True, tool_calling=True,
            context_length=128_000,
            source="Meta via OpenRouter", license="Apache 2.0",
        ),
        ModelInfo(
            provider_id="openrouter",
            model_id="qwen/qwen-2.5-72b",
            display_name="Qwen 2.5 72B",
            text=True, streaming=True, tool_calling=True, vision=True,
            context_length=131_072,
            source="Alibaba via OpenRouter", license="Apache 2.0",
        ),
    ],
    # Local providers (placeholder models)
    "local": [
        ModelInfo(
            provider_id="local",
            model_id="auto",
            display_name="Auto-detect local models",
            text=True, streaming=True, tool_calling=True,
            vision=True, local=True,
            source="Auto", license="Various",
        ),
    ],
    "ollama": [
        ModelInfo(
            provider_id="ollama",
            model_id="auto",
            display_name="Auto-detect Ollama models",
            text=True, streaming=True, tool_calling=True,
            vision=True, local=True,
            source="Ollama", license="Various",
        ),
    ],
    "llama_cpp": [
        ModelInfo(
            provider_id="llama_cpp",
            model_id="auto",
            display_name="Auto-detect llama.cpp models",
            text=True, streaming=True, tool_calling=True,
            vision=True, local=True,
            source="llama.cpp", license="Various",
        ),
    ],
    "openai_compat": [
        ModelInfo(
            provider_id="openai_compat",
            model_id="auto",
            display_name="Auto-detect OpenAI-compatible models",
            text=True, streaming=True, tool_calling=True,
            vision=True, local=True,
            source="OpenAI-compatible", license="Various",
        ),
    ],
}


# ── Public helpers ──────────────────────────────────────────────────


def list_models_for_provider(provider_id: str) -> list[ModelInfo]:
    """Return the static catalog models for *provider_id*.

    When *provider_id* is not known, returns an empty list so that the
    caller can fall back to a "model not available" message.
    """
    return list(MODEL_CATALOG.get(provider_id, []))


async def discover_models(
    provider_id: str,
    *,
    api_key: str | None = None,
    base_url: str = "",
) -> list[ModelInfo]:
    """Try to discover models from the provider at runtime.

    Returns the catalog models (guaranteed available) and appends any
    additional models discovered via the provider's ``list_models()`` API.
    Deduplicates by model_id.
    """
    catalog = list_models_for_provider(provider_id)
    discovered_ids: set[str] = {m.model_id for m in catalog}

    if provider_id in ("local", "ollama", "llama_cpp"):
        # Local providers do not have a live API endpoint for model listing
        return catalog

    # Dynamic discovery via provider factory
    try:
        from providers.registry import get
        from providers.errors import ProviderError

        factory = get(provider_id)
        provider = factory(
            api_key=api_key,
            base_url=base_url,
        )
        if hasattr(provider, "list_models") and callable(provider.list_models):
            try:
                new_models = await provider.list_models()
            except Exception:  # noqa: BLE001 - network errors are non-blocking
                new_models = []

            for m in new_models:
                if m.model_id not in discovered_ids:
                    catalog.append(m)
                    discovered_ids.add(m.model_id)
    except ProviderError:
        # Not registered — nothing to do
        pass
    except Exception:  # noqa: BLE001 - unexpected errors are non-blocking
        pass

    return catalog


def model_is_available(model: ModelInfo) -> bool:
    """Return True when the model can actually be used for chat.

    A model must have at least ``text`` capability.
    """
    return bool(model.text)


def filter_available_models(models: list[ModelInfo]) -> list[ModelInfo]:
    """Return only models suitable for chat usage."""
    return [m for m in models if model_is_available(m)]


def format_capabilities(model: ModelInfo) -> list[str]:
    """Return human-readable capability labels for a model."""
    caps: list[str] = []
    if model.tool_calling:
        caps.append("Tool calling")
    if model.vision:
        caps.append("Vision")
    if model.structured_output:
        caps.append("Structured output")
    if model.audio_input:
        caps.append("Audio input")
    if model.audio_output:
        caps.append("Audio output")
    if model.streaming:
        caps.append("Streaming")
    if model.embeddings:
        caps.append("Embeddings")
    if model.local:
        caps.append("Local")
    return caps
