"""Gemini Live client factory. The only Live SDK import surface."""

from __future__ import annotations

from typing import Any

__all__ = ["create_live_client", "types"]


class _LazyTypes:
    """Import `google.genai.types` on first attribute access, not at import time."""

    _mod: Any = None

    def _load(self) -> Any:
        if self._mod is None:
            from google.genai import types as real

            self._mod = real
        return self._mod

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)


types = _LazyTypes()


def __getattr__(name: str) -> Any:
    if name == "genai":
        from google import genai

        return genai
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_live_client(*, api_key: str, http_options: dict | None = None):
    """Construct the Gemini Live client. Callers must not import google.genai.

    Fail-closed when settings forbid cloud (offline / local_only / fully_local).
    The SDK is imported only after the cloud gate so offline tests do not
    require a working vision extra.
    """
    from config.schema import settings_forbid_cloud

    if settings_forbid_cloud():
        raise RuntimeError("Live client is disabled in local_only/offline/fully_local")
    from google import genai

    options = http_options or {"api_version": "v1beta"}
    return genai.Client(api_key=api_key, http_options=options)  # type: ignore[arg-type]
