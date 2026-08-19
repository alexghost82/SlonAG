"""Provider-test fixtures. Isolated from config secrets and the network."""

from __future__ import annotations

import pytest

from config.schema import PROVIDER_IDS
from providers.registry import clear, register

from tests.unit.providers.mocks import MockChatProvider


@pytest.fixture
def clean_registry():
    """Empty the process-wide registry around each test."""
    clear()
    yield
    clear()


@pytest.fixture
def registered_mocks(clean_registry):
    """Register in-memory factories for the four known provider ids."""
    for provider_id in sorted(PROVIDER_IDS):
        register(provider_id, _factory_for(provider_id))
    return tuple(sorted(PROVIDER_IDS))


def _factory_for(provider_id: str):
    def factory() -> MockChatProvider:
        return MockChatProvider(provider_id)

    factory.provider_id = provider_id  # type: ignore[attr-defined]
    return factory
