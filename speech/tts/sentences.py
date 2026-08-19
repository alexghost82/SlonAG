"""Split normalized TTS text into speakable sentences."""

from __future__ import annotations

import re

# Split after a sentence terminator when the next character is whitespace.
# Consecutive dots in "..." stay with the current sentence.
_SPLIT = re.compile(r"(?<=[.!?…])(?!\.)\s+")


def split_sentences(text: str) -> list[str]:
    """Return non-empty sentence chunks, preserving trailing punctuation."""
    if not isinstance(text, str):
        raise TypeError("split_sentences() expected a string")
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in _SPLIT.split(stripped) if part.strip()]
