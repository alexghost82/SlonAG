"""App-unit fixtures. No display, no live secrets, no network."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from localization.translator import reset_locale


@pytest.fixture(autouse=True)
def russian_default_locale() -> Iterator[None]:
    reset_locale()
    yield
    reset_locale()
