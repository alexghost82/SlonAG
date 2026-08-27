"""Shared fixtures for browser integration tests."""

from __future__ import annotations

import pytest

from runtime.browser.service import BrowserService


@pytest.fixture()
def browser_service():
    """Shared browser service for tests that need their own lifecycle."""
    svc = BrowserService()
    svc.start()
    yield svc
    svc.stop()
