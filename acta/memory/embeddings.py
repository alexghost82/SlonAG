"""Local embeddings hook. Cloud embedders stay unused in offline profiles."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

PRIVACY_FULLY_LOCAL = "fully_local"
NETWORK_OFFLINE = "offline"


@runtime_checkable
class Embedder(Protocol):
    """Injected embedder. ``is_local`` is the only cloud/local signal."""

    is_local: bool

    def embed(self, text: str) -> Sequence[float]: ...


class EmbeddingService:
    """Call an injected embedder only when the privacy profile allows it."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        privacy_profile: str = PRIVACY_FULLY_LOCAL,
        network_mode: str = NETWORK_OFFLINE,
    ) -> None:
        self._embedder = embedder
        self.privacy_profile = privacy_profile
        self.network_mode = network_mode

    @property
    def embedder(self) -> Embedder | None:
        return self._embedder

    def must_stay_local(self) -> bool:
        return (
            self.privacy_profile == PRIVACY_FULLY_LOCAL
            or self.network_mode == NETWORK_OFFLINE
        )

    def embed(self, text: str) -> list[float] | None:
        """Return a vector, or None when embedding is skipped or blocked."""
        embedder = self._embedder
        if embedder is None:
            return None
        if self.must_stay_local() and not embedder.is_local:
            return None
        return list(embedder.embed(text))


__all__ = [
    "NETWORK_OFFLINE",
    "PRIVACY_FULLY_LOCAL",
    "Embedder",
    "EmbeddingService",
]
