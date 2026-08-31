"""Gemini serialization for canonical tool specifications."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from acta.tools.contracts import ToolSpec


def _live_compatible_schema(value: object) -> object:
    """Copy JSON Schema while removing keywords rejected by Gemini Live."""
    if isinstance(value, dict):
        return {
            key: _live_compatible_schema(item)
            for key, item in value.items()
            if key != "additionalProperties"
        }
    if isinstance(value, list):
        return [_live_compatible_schema(item) for item in value]
    return deepcopy(value)


def export_gemini_tools(specs: Sequence[ToolSpec]) -> list[dict[str, object]]:
    """Return declarations suitable for Gemini's ``function_declarations``.

    The result deliberately contains plain Python values rather than Google SDK
    types so importing the canonical tool runtime never requires that SDK.
    """

    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": _live_compatible_schema(dict(spec.input_schema)),
        }
        for spec in specs
    ]


__all__ = ["export_gemini_tools"]
