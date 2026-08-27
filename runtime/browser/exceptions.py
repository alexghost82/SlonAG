"""Browser error hierarchy."""
from __future__ import annotations


class BrowserError(Exception):
    """Base exception for all browser runtime errors."""


class BrowserLaunchError(BrowserError):
    """Browser or Playwright cannot be launched."""


class BrowserTimeoutError(BrowserError):
    """Action timed out."""


class BrowserPageError(BrowserError):
    """Page/Tab operation failed."""


class BrowserNavigationError(BrowserError):
    """Navigation failed."""


class BrowserElementError(BrowserError):
    """Element operation (click, type, etc.) failed."""


class BrowserDownloadError(BrowserError):
    """Download operation failed."""
