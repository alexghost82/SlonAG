"""Parse an OpenRouter ``/models`` (or ``/api/v1/models``) JSON payload."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from providers.contracts import ModelInfo

from providers.openrouter.errors import PROVIDER_ID


def parse_models_payload(payload: object) -> list[ModelInfo]:
    """Turn a mocked or live catalog document into ``ModelInfo`` rows.

    Capability flags are conservative: vision/audio/tools are set only when
    the payload says so. Unknown or malformed entries are skipped.
    """
    models: list[ModelInfo] = []
    for item in _iter_model_dicts(payload):
        parsed = _parse_model(item)
        if parsed is not None:
            models.append(parsed)
    return models


def _iter_model_dicts(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items: object = payload
    elif isinstance(payload, Mapping):
        items = payload.get("data", payload.get("models", []))
    else:
        return []
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            result.append(dict(item))
    return result


def _parse_model(item: Mapping[str, Any]) -> ModelInfo | None:
    model_id = item.get("id") or item.get("name")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    display = item.get("name")
    display_name = display if isinstance(display, str) and display.strip() else model_id

    architecture = item.get("architecture")
    arch = architecture if isinstance(architecture, Mapping) else {}
    input_mods = _modality_set(arch.get("input_modalities"))
    output_mods = _modality_set(arch.get("output_modalities"))
    modality = str(arch.get("modality") or "").lower()

    if not input_mods:
        if "image" in modality:
            input_mods.add("image")
        if "text" in modality:
            input_mods.add("text")
        if "audio" in modality.split("->", 1)[0]:
            input_mods.add("audio")
    if not output_mods:
        outgoing = modality.split("->", 1)[-1] if "->" in modality else modality
        if "text" in outgoing:
            output_mods.add("text")
        if "embed" in outgoing:
            output_mods.add("embeddings")
        if "audio" in outgoing:
            output_mods.add("audio")

    supported_params = _parameter_set(item.get("supported_parameters"))

    is_embedding = (
        "embeddings" in output_mods
        or "embed" in model_id.lower()
        or "embedding" in display_name.lower()
    )
    has_text_io = "text" in input_mods or "text" in output_mods
    text = (not is_embedding) and (has_text_io or not (input_mods or output_mods))
    vision = "image" in input_mods
    audio_input = "audio" in input_mods
    audio_output = "audio" in output_mods
    tool_calling = bool({"tools", "tool_choice"} & supported_params)
    structured_output = bool({"response_format", "structured_outputs"} & supported_params)

    return ModelInfo(
        provider_id=PROVIDER_ID,
        model_id=model_id,
        display_name=display_name,
        text=text,
        streaming=text and not is_embedding,
        structured_output=structured_output,
        tool_calling=tool_calling,
        vision=vision,
        audio_input=audio_input,
        audio_output=audio_output,
        embeddings=is_embedding,
        context_length=_as_int(item.get("context_length")),
        local=False,
        source="openrouter",
        license="",
        cost=_optional_prompt_cost(item.get("pricing")),
    )


def _modality_set(value: object) -> set[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return set()
    return {str(item).lower() for item in value if item}


def _parameter_set(value: object) -> set[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return set()
    return {str(item).lower() for item in value if item}


def _as_int(value: object) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, str)):
            return int(value)
        return 0
    except (TypeError, ValueError):
        return 0


def _optional_prompt_cost(pricing: object) -> float | None:
    if not isinstance(pricing, Mapping):
        return None
    raw = pricing.get("prompt")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
