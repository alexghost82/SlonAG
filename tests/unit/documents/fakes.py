"""In-memory parser and STT hooks. Never download, exec, or touch the network."""

from __future__ import annotations


class FakeExtractor:
    """Records payload bytes and returns configured text."""

    def __init__(self, text: str = "extracted") -> None:
        self.text = text
        self.calls: list[bytes] = []

    def __call__(self, data: bytes) -> str:
        self.calls.append(data)
        return self.text


class ExplodingExtractor:
    """Raises after the caller has already written a temp file."""

    def __init__(self, message: str = "extractor failed") -> None:
        self.message = message
        self.calls: list[bytes] = []

    def __call__(self, data: bytes) -> str:
        self.calls.append(data)
        raise RuntimeError(self.message)
