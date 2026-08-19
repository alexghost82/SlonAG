"""In-process embedders for memory tests. No network and no model files."""

from __future__ import annotations


class FakeLocalEmbedder:
    """Records embed calls and returns a fixed local vector."""

    is_local = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.25, 0.5, 0.75]


class FakeCloudEmbedder:
    """Cloud-shaped embedder used to prove offline profiles never call it."""

    is_local = False

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, 0.0]
