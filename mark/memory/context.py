"""Bounded context assembly for AgentLoop prompt injection.

Turns RetrievalResult chunks into a memory context block that fits within
a configurable token budget and is safe to inject before the system prompt.
"""

from __future__ import annotations

from mark.memory.errors import MemoryPolicyError
from mark.memory.policy import MemoryPolicy
from mark.memory.retriever import ContextChunk, RetrievalResult


MAX_MEMORY_CHUNKS = 10
DEFAULT_MEMORY_PREFIX = "# CONTEXT — PERSONAL MEMORY (trustworthy, up-to-date)"


class MemoryContextAssembler:
    """Assemble memory chunks into a bounded context block for prompt injection."""

    def __init__(
        self,
        *,
        policy: MemoryPolicy | None = None,
        max_chunks: int = MAX_MEMORY_CHUNKS,
        prefix: str = DEFAULT_MEMORY_PREFIX,
        include_scores: bool = False,
    ) -> None:
        self._policy = policy or MemoryPolicy()
        self._max_chunks = max_chunks
        self._prefix = prefix
        self._include_scores = include_scores

    def assemble(self, result: RetrievalResult) -> str:
        """Turn a RetrievalResult into a memory context string.

        Returns an empty string when there are no chunks.
        """
        if not result.chunks:
            return ""

        lines: list[str] = [self._prefix]
        seen: set[str] = set()

        for chunk in result.chunks[: self._max_chunks]:
            # Re-check privacy (belt-and-suspenders)
            try:
                self._policy.check(
                    chunk.source_ref.split(":")[0] if ":" in chunk.source_ref else "check",
                    chunk.text,
                )
            except MemoryPolicyError:
                continue

            text = chunk.text
            if text in seen:
                continue
            seen.add(text)

            if self._include_scores:
                score_note = (
                    f" (rel={chunk.relevance:.2f} conf={chunk.confidence:.2f} rec={chunk.recency:.2f})"
                )
                lines.append(f"- {text}{score_note}")
            else:
                lines.append(f"- {text}")

        if not lines or len(lines) == 1:
            return ""

        return "\n".join(lines)

    def assemble_chunks(self, chunks: list[ContextChunk]) -> str:
        """Directly assemble chunks (bypassing RetrievalResult)."""
        result = RetrievalResult(chunks=chunks)
        return self.assemble(result)


def build_system_prompt_with_memory(
    base_system_prompt: str,
    memory_context: str,
    *,
    sep: str = "\n\n",
) -> str:
    """Prepend memory context to an existing system prompt."""
    if not memory_context:
        return base_system_prompt
    return memory_context + sep + base_system_prompt


__all__ = [
    "DEFAULT_MEMORY_PREFIX",
    "MAX_MEMORY_CHUNKS",
    "MemoryContextAssembler",
    "build_system_prompt_with_memory",
]
