"""SlonAG browser runtime — deterministic, cancellable Playwright service.

Public API:
    - BrowserService (singleton via get_browser_service())
    - BrowserStatus (dataclass)
    - BrowserError (exception hierarchy)
"""
from __future__ import annotations

from runtime.browser.status import BrowserStatus, BrowserErrorCode
from runtime.browser.service import BrowserService, get_browser_service
from runtime.browser.exceptions import BrowserError, BrowserLaunchError, BrowserTimeoutError

__all__ = [
    "BrowserService",
    "BrowserStatus",
    "BrowserErrorCode",
    "BrowserError",
    "BrowserLaunchError",
    "BrowserTimeoutError",
    "get_browser_service",
]
