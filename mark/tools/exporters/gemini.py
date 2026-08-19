"""Gemini serialization for canonical tool specifications."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from mark.tools.contracts import ToolSpec


def export_gemini_tools(specs: Sequence[ToolSpec]) -> list[dict[str, object]]:
    """Return declarations suitable for Gemini's ``function_declarations``.

    The result deliberately contains plain Python values rather than Google SDK
    types so importing the canonical tool runtime never requires that SDK.
    """

    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": deepcopy(dict(spec.input_schema)),
        }
        for spec in specs
    ]


__all__ = ["export_gemini_tools"]
