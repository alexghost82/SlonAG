"""Vision engine interface.

This module provides the `build_engine` factory that production code
imports. In tests the factory is mocked to return a deterministic engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class VisionEngine:
    """Minimal vision engine interface for local analysis."""

    def analyze(self, image_bytes: bytes, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        """Analyze an image and return labels/text."""
        raise NotImplementedError("Subclasses must implement analyze()")


class LocalVisionEngine(VisionEngine):
    """Stub local vision engine for offline use."""

    def analyze(self, image_bytes: bytes, prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        return {
            "labels": [],
            "text": "",
            "prompt": prompt,
        }


def build_engine(**kwargs: Any) -> VisionEngine:
    """Build and return a VisionEngine instance.

    Production code calls this to obtain a vision engine.
    Tests typically patch this function to return a MagicMock.
    """
    return LocalVisionEngine()
