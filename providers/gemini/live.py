"""Gemini Live client factory. The only Live SDK import surface."""

from __future__ import annotations

from google import genai
from google.genai import types

__all__ = ["create_live_client", "genai", "types"]


def create_live_client(*, api_key: str, http_options: dict | None = None):
    """Construct the Gemini Live client. Callers must not import google.genai."""
    options = http_options or {"api_version": "v1beta"}
    return genai.Client(api_key=api_key, http_options=options)
