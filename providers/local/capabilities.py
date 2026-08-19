"""Conservative capability discovery for local language models.

The local server protocol describes what an endpoint *can transport*.  It does
not, by itself, prove that a particular model can use tools or vision.  This
module therefore only enables advanced features when model-specific metadata,
an explicit override, or the small built-in model table says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LocalModelCapabilities:
    text: bool = True
    streaming: bool = True
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    context_length: int = 0


_BOOLEAN_FIELDS = frozenset(
    {"text", "streaming", "tool_calling", "structured_output", "vision"}
)
_FIELDS = _BOOLEAN_FIELDS | {"context_length"}

# These entries intentionally identify model families, rather than protocols.
# Keep this table small: an unknown family always receives conservative defaults.
_KNOWN_MODEL_OVERRIDES: Mapping[tuple[str, str], Mapping[str, object]] = {
    ("ollama", "llama3.1"): {"tool_calling": True},
    ("ollama", "llama3.2"): {"tool_calling": True},
    ("ollama", "qwen2.5"): {"tool_calling": True},
}

_CAPABILITY_NAMES = {
    "tools": "tool_calling",
    "tool_calling": "tool_calling",
    "structured_output": "structured_output",
    "vision": "vision",
}


def resolve_local_capabilities(
    provider_id: str,
    model_id: str,
    runtime_metadata: Mapping[str, object] | None,
    overrides: Mapping[str, object] | None = None,
) -> LocalModelCapabilities:
    """Resolve local model capabilities with per-field precedence.

    Values are merged from lowest to highest priority: conservative defaults,
    known model-family facts, explicit user overrides, then runtime-reported
    model metadata.  A higher-priority source wins only for fields it explicitly
    and validly provides.  Malformed runtime metadata is untrusted and ignored;
    malformed explicit overrides raise ``ValueError`` so configuration errors do
    not silently weaken or broaden the selected model's contract.
    """

    values = asdict(LocalModelCapabilities())
    values.update(_known_capabilities(provider_id, model_id))
    if overrides is not None:
        values.update(_validated_fields(overrides, strict=True))
    if runtime_metadata is not None:
        values.update(_runtime_fields(runtime_metadata))
    return LocalModelCapabilities(**values)


def _known_capabilities(provider_id: str, model_id: str) -> dict[str, object]:
    normalized_provider = provider_id.strip().lower()
    normalized_model = model_id.strip().lower()
    # Ollama tags (for example ``llama3.1:8b``) share family capabilities.
    family = normalized_model.split(":", 1)[0]
    known = _KNOWN_MODEL_OVERRIDES.get((normalized_provider, family), {})
    return dict(known)


def _runtime_fields(metadata: Mapping[str, object]) -> dict[str, object]:
    resolved: dict[str, object] = {}
    nested = metadata.get("capabilities")
    if isinstance(nested, Mapping):
        resolved.update(_validated_fields(nested, strict=False))
    elif isinstance(nested, (list, tuple, set, frozenset)):
        names = {item.strip().lower() for item in nested if isinstance(item, str)}
        for wire_name, field_name in _CAPABILITY_NAMES.items():
            if wire_name in names:
                resolved[field_name] = True

    # Direct model fields are the most explicit form within runtime metadata.
    resolved.update(_validated_fields(metadata, strict=False))
    return resolved


def _validated_fields(
    source: Mapping[str, object], *, strict: bool
) -> dict[str, object]:
    resolved: dict[str, object] = {}
    for key, value in source.items():
        if key not in _FIELDS:
            continue
        valid = (
            isinstance(value, bool)
            if key in _BOOLEAN_FIELDS
            else isinstance(value, int) and not isinstance(value, bool) and value >= 0
        )
        if not valid:
            if strict:
                expected = (
                    "a boolean"
                    if key in _BOOLEAN_FIELDS
                    else "a non-negative integer"
                )
                raise ValueError(f"local model override {key!r} must be {expected}")
            continue
        resolved[key] = value
    return resolved


__all__ = ["LocalModelCapabilities", "resolve_local_capabilities"]
