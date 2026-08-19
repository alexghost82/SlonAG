"""In-process registry of provider factory callables.

Factories are stored, not invoked. This module does not construct cloud
clients and does not read API keys.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from providers.errors import ProviderError

ProviderFactory = Callable[..., Any]

_FACTORIES: dict[str, ProviderFactory] = {}


def register(provider_id: str, factory: ProviderFactory) -> None:
    """Associate ``provider_id`` with a factory callable."""
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ProviderError("provider_id must be a non-empty string")
    if not callable(factory):
        raise ProviderError("factory must be callable")
    _FACTORIES[provider_id] = factory


def get(provider_id: str) -> ProviderFactory:
    """Return the factory for ``provider_id``.

    Raises ``ProviderError`` when the id has not been registered.
    """
    try:
        return _FACTORIES[provider_id]
    except KeyError:
        raise ProviderError(f"unknown provider_id {provider_id!r}") from None


def registered_ids() -> tuple[str, ...]:
    """Return registered provider ids in sorted order."""
    return tuple(sorted(_FACTORIES))


def clear() -> None:
    """Remove all registrations. Intended for tests."""
    _FACTORIES.clear()
