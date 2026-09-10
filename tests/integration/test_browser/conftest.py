"""Shared fixtures for browser integration tests."""

from __future__ import annotations

import pytest

from runtime.browser.exceptions import BrowserLaunchError
from runtime.browser.service import BrowserService
from runtime.browser.status import BrowserAvailability, detect_runtime_availability

_PLAYWRIGHT_USABLE: bool | None = None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "playwright: requires Playwright Chromium (CI installs it)")


def skip_unless_playwright_ready() -> None:
    global _PLAYWRIGHT_USABLE
    if detect_runtime_availability() != BrowserAvailability.READY:
        pytest.skip("Playwright Chromium not installed")
    if _PLAYWRIGHT_USABLE is False:
        pytest.skip("Playwright Chromium not installed")


def mark_playwright_unusable() -> None:
    global _PLAYWRIGHT_USABLE
    _PLAYWRIGHT_USABLE = False


def _skip_unless_playwright_ready() -> None:
    skip_unless_playwright_ready()


@pytest.fixture()
def browser_service():
    """Shared browser service for tests that need their own lifecycle."""
    _skip_unless_playwright_ready()
    svc = BrowserService()
    try:
        svc.start()
    except BrowserLaunchError as exc:
        mark_playwright_unusable()
        pytest.skip(f"Playwright Chromium not installed: {exc}")
    yield svc
    svc.stop()
