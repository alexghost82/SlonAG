"""Static Gemini model catalog.

This list is advertised by ``list_models`` only. Chat and stream send the
caller-selected ``model_id`` and never walk these entries as fallbacks.
"""

from __future__ import annotations

from providers.contracts import ModelInfo

PROVIDER_ID = "gemini"

GEMINI_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        provider_id=PROVIDER_ID,
        model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        text=True,
        streaming=True,
        structured_output=True,
        tool_calling=True,
        vision=True,
        audio_input=False,
        audio_output=False,
        embeddings=False,
        context_length=1_048_576,
        local=False,
        source="Google",
        license="Proprietary",
    ),
    ModelInfo(
        provider_id=PROVIDER_ID,
        model_id="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        text=True,
        streaming=True,
        structured_output=True,
        tool_calling=True,
        vision=True,
        audio_input=False,
        audio_output=False,
        embeddings=False,
        context_length=1_048_576,
        local=False,
        source="Google",
        license="Proprietary",
    ),
    ModelInfo(
        provider_id=PROVIDER_ID,
        model_id="gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash-Lite",
        text=True,
        streaming=True,
        structured_output=True,
        tool_calling=True,
        vision=False,
        audio_input=False,
        audio_output=False,
        embeddings=False,
        context_length=1_048_576,
        local=False,
        source="Google",
        license="Proprietary",
    ),
    ModelInfo(
        provider_id=PROVIDER_ID,
        model_id="gemini-embedding-001",
        display_name="Gemini Embedding 001",
        text=False,
        streaming=False,
        structured_output=False,
        tool_calling=False,
        vision=False,
        audio_input=False,
        audio_output=False,
        embeddings=True,
        context_length=8192,
        local=False,
        source="Google",
        license="Proprietary",
    ),
)
