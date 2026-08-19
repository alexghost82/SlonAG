"""In-memory STT engines for unit tests. No microphone, models, or network."""

from __future__ import annotations

from collections.abc import Callable


class FakeEngine:
    """Records ``transcribe`` calls and returns a canned string."""

    def __init__(self, text: str = "привет") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(self, audio: bytes, language: str) -> str:
        self.calls.append((audio, language))
        return self.text


class ExplodingEngine:
    """Fails if the provider reaches the engine."""

    def transcribe(self, audio: bytes, language: str) -> str:
        raise AssertionError("STT engine must not be called")


class PartialEngine:
    """Invokes ``on_partial`` with interim strings when the provider supplies it."""

    def __init__(
        self,
        text: str = "привет",
        partials: tuple[str, ...] = ("при", "привет"),
    ) -> None:
        self.text = text
        self.partials = partials
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(
        self,
        audio: bytes,
        language: str,
        on_partial: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        self.calls.append((audio, language))
        last = ""
        for chunk in self.partials:
            if cancelled is not None and cancelled():
                return last
            last = chunk
            if on_partial is not None:
                on_partial(chunk)
        return self.text
