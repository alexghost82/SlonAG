"""OpenAI-compatible serialization for canonical tool specifications."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from mark.tools.contracts import ToolSpec


def export_openai_tools(specs: Sequence[ToolSpec]) -> list[dict[str, object]]:
    """Return OpenAI function-tool declarations without mutating ``specs``."""

    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": deepcopy(dict(spec.input_schema)),
            },
        }
        for spec in specs
    ]


__all__ = ["export_openai_tools"]
