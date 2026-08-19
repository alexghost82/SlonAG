"""Provider-boundary exporters for canonical tool specifications."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mark.tools.contracts import ToolSpec
from mark.tools.exporters.gemini import export_gemini_tools
from mark.tools.exporters.openai import export_openai_tools

ToolExport = list[dict[str, object]]
ToolExporter = Callable[[Sequence[ToolSpec]], ToolExport]

_OPENAI_COMPATIBLE_PROVIDERS = frozenset(
    {
        "openai",
        "openrouter",
        "ollama",
        "llama_cpp",
        "llama.cpp",
        "local",
        "openai_compatible",
        "openai-compatible",
    }
)


def export_tools(provider_id: str, specs: Sequence[ToolSpec]) -> ToolExport:
    """Export canonical specs using the selected provider's wire convention."""

    normalized_provider = provider_id.strip().lower()
    exporter: ToolExporter
    if normalized_provider == "gemini":
        exporter = export_gemini_tools
    elif normalized_provider in _OPENAI_COMPATIBLE_PROVIDERS:
        exporter = export_openai_tools
    else:
        raise ValueError(f"unsupported tool schema provider: {provider_id!r}")
    return exporter(specs)


__all__ = ["export_gemini_tools", "export_openai_tools", "export_tools"]
